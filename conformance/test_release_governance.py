from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml


REPO = Path(__file__).resolve().parents[1]
PROJECTION = Path("scripts/release_projection.py")
PROVENANCE = Path("scripts/release_provenance.py")
PROJECTED_PATHS = (
    Path("worker/lakefile.lean"),
    Path("dsls/nbdsl/lakefile.lean"),
    Path("nbdsl_kernel/pyproject.toml"),
    Path("jupyterlab_nbdsl/package.json"),
    Path("worker/lean-toolchain"),
    Path("dsls/nbdsl/lean-toolchain"),
    Path("worker/Worker/ReleaseInfo.lean"),
    Path("dsls/nbdsl/lake-manifest.json"),
)


def test_ci_uses_one_immutable_qc_revision_and_records_it() -> None:
    workflow = yaml.safe_load((REPO / ".github/workflows/ci.yml").read_text())
    dsl_job = workflow["jobs"]["dsl"]
    qc_revision = dsl_job.get("env", {}).get("AI_REVIEW_CI_SHA")
    assert isinstance(qc_revision, str)
    assert len(qc_revision) == 40
    assert set(qc_revision) <= set("0123456789abcdef")

    steps = {
        step.get("name"): step
        for step in dsl_job["steps"]
        if "name" in step
    }
    mypy_command = steps[
        "mypy (strict, mirrors ai-review-ci's global config)"
    ]["run"]
    consumer_qc_command = steps[
        "provision the global QC justfiles the consumer gate delegates to"
    ]["run"]
    qualification = steps[
        "qualify the exact kernel candidate against the frozen consumer"
    ]

    assert "$AI_REVIEW_CI_SHA" in mypy_command
    assert "$AI_REVIEW_CI_SHA" in consumer_qc_command
    assert qualification.get("env", {}).get(
        "AI_REVIEW_CI_SHA"
    ) == qc_revision
    assert '"ai_review_ci_sha": "$AI_REVIEW_CI_SHA"' in (
        REPO / "scripts/qualify_consumer.sh"
    ).read_text()


def copy_release_projection(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for relative in (Path("release.toml"), PROJECTION, *PROJECTED_PATHS):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / relative, target)
    return root


def run_projection(root: Path, mode: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(root / PROJECTION),
            mode,
            "--root",
            str(root),
        ],
        capture_output=True,
        check=False,
        text=True,
    )


@pytest.mark.parametrize(
    ("section", "field"),
    (
        (None, "schema"),
        ("compat", "plugin_api"),
        ("compat", "wire_protocol"),
    ),
)
def test_projection_rejects_boolean_integer_contract_fields(
    tmp_path: Path,
    section: str | None,
    field: str,
) -> None:
    root = copy_release_projection(tmp_path)
    release_path = root / "release.toml"
    release = tomllib.loads(release_path.read_text())
    old_value = release[field] if section is None else release[section][field]
    release_path.write_text(
        release_path.read_text().replace(
            f"{field} = {old_value}",
            f"{field} = true",
            1,
        )
    )
    parsed = tomllib.loads(release_path.read_text())
    actual = parsed[field] if section is None else parsed[section][field]
    assert actual is True

    completed = run_projection(root, "write")

    assert completed.returncode != 0


def test_projection_accepts_exact_integer_contract_fields(tmp_path: Path) -> None:
    root = copy_release_projection(tmp_path)
    release = tomllib.loads((root / "release.toml").read_text())

    assert type(release["schema"]) is int
    assert type(release["compat"]["plugin_api"]) is int
    assert type(release["compat"]["wire_protocol"]) is int
    assert run_projection(root, "check").returncode == 0


def drift_mathlib_lock(root: Path) -> dict[str, object]:
    manifest_path = root / "dsls/nbdsl/lake-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    mathlib = next(
        package for package in manifest["packages"]
        if package["name"] == "mathlib"
    )
    original = dict(mathlib)
    mathlib["inputRev"] = "v0.0.0-release-governance-red"
    mathlib["rev"] = "0" * 40
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return original


def test_projection_check_rejects_mathlib_lock_drift(tmp_path: Path) -> None:
    root = copy_release_projection(tmp_path)
    drift_mathlib_lock(root)

    completed = run_projection(root, "check")

    assert completed.returncode != 0


def test_projection_write_restores_the_lake_resolved_mathlib_lock(
    tmp_path: Path,
) -> None:
    root = copy_release_projection(tmp_path)
    expected_mathlib = drift_mathlib_lock(root)

    completed = run_projection(root, "write")

    assert completed.returncode == 0
    manifest = json.loads(
        (root / "dsls/nbdsl/lake-manifest.json").read_text()
    )
    actual_mathlib = next(
        package for package in manifest["packages"]
        if package["name"] == "mathlib"
    )
    assert actual_mathlib == expected_mathlib


def initialise_provenance_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    empty_hooks = tmp_path / "empty-hooks"
    empty_hooks.mkdir()
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(REPO / PROVENANCE, root / PROVENANCE)
    shutil.copy2(REPO / "release.toml", root / "release.toml")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "Release Test"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "release@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "core.hooksPath", str(empty_hooks)],
        check=True,
    )
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "-m", "release fixture"],
        check=True,
    )
    return root


def run_provenance(
    root: Path,
    *args: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(root / PROVENANCE), *args],
        capture_output=True,
        check=False,
        text=True,
    )


def test_provenance_rejects_duplicate_distribution_basenames(
    tmp_path: Path,
) -> None:
    root = initialise_provenance_repo(tmp_path)
    artifacts = tmp_path / "artifacts"
    worker = artifacts / "worker"
    first = artifacts / "first" / "package.whl"
    second = artifacts / "second" / "package.whl"
    for path, content in (
        (worker, b"worker"),
        (first, b"first distribution"),
        (second, b"second distribution"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    completed = run_provenance(
        root,
        "generate",
        "--worker",
        str(worker),
        "--dist",
        str(first),
        "--dist",
        str(second),
        "--out",
        str(tmp_path / "provenance.json"),
    )

    assert completed.returncode != 0


def test_default_generated_provenance_is_the_only_cleanliness_exception(
    tmp_path: Path,
) -> None:
    root = initialise_provenance_repo(tmp_path)
    worker = tmp_path / "artifacts" / "worker"
    worker.parent.mkdir()
    worker.write_bytes(b"worker")

    generated = run_provenance(root, "generate", "--worker", str(worker))

    assert generated.returncode == 0
    provenance_path = root / "release-provenance.json"
    recorded = json.loads(provenance_path.read_text())
    assert recorded["worker_binary"]["sha256"]
    status = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        capture_output=True,
        check=True,
        text=True,
    )
    assert status.stdout.splitlines() == ["?? release-provenance.json"]

    verified = run_provenance(
        root,
        "verify",
        "--worker",
        str(worker),
        "--provenance",
        str(provenance_path),
    )

    assert verified.returncode == 0
