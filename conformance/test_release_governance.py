from __future__ import annotations

import hashlib
import json
import os
import re
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


def test_release_tag_is_data_never_shell_source() -> None:
    workflow = yaml.safe_load(
        (REPO / ".github/workflows/release.yml").read_text()
    )
    publish = workflow["jobs"]["publish"]
    assert publish["env"]["RELEASE_TAG"] == "${{ github.ref_name }}"
    for step in publish["steps"]:
        if command := step.get("run"):
            assert "${{ github.ref_name }}" not in command


def test_release_verifies_tag_and_main_ancestry_before_publish() -> None:
    workflow = yaml.safe_load(
        (REPO / ".github/workflows/release.yml").read_text()
    )
    steps = workflow["jobs"]["publish"]["steps"]
    publish_index = next(
        index for index, step in enumerate(steps)
        if step.get("name") == "publish the GitHub release"
    )
    before_publish = "\n".join(
        step.get("run", "") for step in steps[:publish_index]
    )
    publish = steps[publish_index]["run"]

    assert "commits/$RELEASE_TAG" in before_publish
    assert "merge-base --is-ancestor" in before_publish
    assert "origin/main" in before_publish
    assert "--verify-tag" in publish


def test_ci_executes_each_repository_owned_proof_surface() -> None:
    workflow = yaml.safe_load((REPO / ".github/workflows/ci.yml").read_text())
    commands = "\n".join(
        step.get("run", "")
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
    )

    for proof in (
        "conformance/test_runner_contracts.py",
        "nbdsl_kernel/tests/test_inspect.py",
        "nbdsl_kernel/tests/sandbox_check.py",
    ):
        assert proof in commands


def test_ci_uses_one_immutable_qc_revision_and_records_it() -> None:
    workflow = yaml.safe_load((REPO / ".github/workflows/ci.yml").read_text())
    qc_revision = workflow["env"]["AI_REVIEW_CI_SHA"]
    assert re.fullmatch(r"[0-9a-f]{40}", qc_revision)

    dsl_steps = {
        step.get("name"): step
        for step in workflow["jobs"]["dsl"]["steps"]
        if "name" in step
    }
    compat_steps = {
        step.get("name"): step
        for step in workflow["jobs"]["compat"]["steps"]
        if "name" in step
    }
    mypy_command = dsl_steps[
        "mypy (strict, mirrors ai-review-ci's global config)"
    ]["run"]
    consumer_qc_command = compat_steps[
        "provision the global QC justfiles the consumer gate delegates to"
    ]["run"]
    qualification_command = compat_steps[
        "qualify the exact kernel candidate against the frozen consumer"
    ]["run"]

    assert "/ai-review-ci/${AI_REVIEW_CI_SHA}/tool-configs/" in mypy_command
    assert 'origin "$AI_REVIEW_CI_SHA"' in consumer_qc_command
    assert 'rev-parse HEAD)" = "$AI_REVIEW_CI_SHA"' in consumer_qc_command
    assert "scripts/qualify_consumer.sh" in qualification_command
    assert '.ai_review_ci_sha == $expected' in qualification_command
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


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("lean", 'lean = ""'),
        ("plugin_api", "plugin_api = -1"),
        ("wire_protocol", "wire_protocol = -1"),
    ),
)
def test_projection_rejects_invalid_generated_values_before_writes(
    tmp_path: Path,
    field: str,
    replacement: str,
) -> None:
    root = copy_release_projection(tmp_path)
    release_path = root / "release.toml"
    release_path.write_text(re.sub(
        rf"(?m)^{field} = .+$",
        replacement,
        release_path.read_text(),
        count=1,
    ))
    before = {
        path: (root / path).read_bytes()
        for path in PROJECTED_PATHS
    }

    completed = run_projection(root, "write")

    assert completed.returncode != 0
    assert {
        path: (root / path).read_bytes()
        for path in PROJECTED_PATHS
    } == before


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("url", "https://example.invalid/not-mathlib.git"),
        ("type", "path"),
    ),
)
def test_projection_check_rejects_mathlib_source_identity_drift(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    root = copy_release_projection(tmp_path)
    manifest_path = root / "dsls/nbdsl/lake-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    mathlib = next(
        package for package in manifest["packages"]
        if package["name"] == "mathlib"
    )
    mathlib[field] = value
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    assert run_projection(root, "check").returncode != 0


def test_projection_write_is_atomic_when_manifest_is_invalid(
    tmp_path: Path,
) -> None:
    root = copy_release_projection(tmp_path)
    release_path = root / "release.toml"
    release_path.write_text(
        release_path.read_text().replace('version = "1.1.0"',
                                         'version = "1.1.1"', 1)
    )
    manifest_path = root / "dsls/nbdsl/lake-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["packages"] = [
        package for package in manifest["packages"]
        if package.get("name") != "mathlib"
    ]
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    before = {
        path: (root / path).read_bytes()
        for path in PROJECTED_PATHS
    }

    completed = run_projection(root, "write")

    assert completed.returncode != 0
    assert {
        path: (root / path).read_bytes()
        for path in PROJECTED_PATHS
    } == before


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
    assert recorded["worker_binary"]["sha256"] == hashlib.sha256(
        b"worker"
    ).hexdigest()

    verified = run_provenance(
        root,
        "verify",
        "--worker",
        str(worker),
        "--provenance",
        str(provenance_path),
    )

    assert verified.returncode == 0


def test_supplied_untracked_release_artifacts_are_not_source_dirt(
    tmp_path: Path,
) -> None:
    root = initialise_provenance_repo(tmp_path)
    artifacts = root / "artifacts"
    worker = artifacts / "nbdsl_worker"
    distribution = artifacts / "nbdsl_kernel.whl"
    provenance = artifacts / "release-provenance.json"
    artifacts.mkdir()
    worker.write_bytes(b"worker")
    distribution.write_bytes(b"wheel")

    generated = run_provenance(
        root,
        "generate",
        "--worker",
        str(worker),
        "--dist",
        str(distribution),
        "--out",
        str(provenance),
    )

    assert generated.returncode == 0, generated.stderr
    verified = run_provenance(
        root,
        "verify",
        "--worker",
        str(worker),
        "--dist",
        str(distribution),
        "--provenance",
        str(provenance),
    )
    assert verified.returncode == 0, verified.stderr


def test_provenance_rejects_other_dirt_beside_selected_record(
    tmp_path: Path,
) -> None:
    root = initialise_provenance_repo(tmp_path)
    worker = tmp_path / "artifacts" / "worker"
    worker.parent.mkdir()
    worker.write_bytes(b"worker")
    generated = run_provenance(root, "generate", "--worker", str(worker))
    assert generated.returncode == 0
    (root / "unrelated.txt").write_text("not a release artifact\n")

    verified = run_provenance(
        root,
        "verify",
        "--worker",
        str(worker),
        "--provenance",
        str(root / "release-provenance.json"),
    )

    assert verified.returncode != 0


def test_provenance_never_exempts_tracked_source_named_as_artifact(
    tmp_path: Path,
) -> None:
    root = initialise_provenance_repo(tmp_path)
    worker = tmp_path / "artifacts" / "worker"
    worker.parent.mkdir()
    worker.write_bytes(b"worker")
    tracked_source = root / "release.toml"
    tracked_source.write_text(tracked_source.read_text() + "\n")

    generated = run_provenance(
        root,
        "generate",
        "--worker",
        str(worker),
        "--dist",
        str(tracked_source),
        "--out",
        str(tmp_path / "release-provenance.json"),
    )

    assert generated.returncode != 0
    assert "dirty tree" in generated.stderr


@pytest.mark.parametrize(
    ("path", "replacement"),
    (
        (("schema",), True),
        (("release", "plugin_api"), 1.0),
        (("release", "wire_protocol"), True),
    ),
)
def test_provenance_verification_rejects_noncanonical_integer_scalars(
    tmp_path: Path,
    path: tuple[str, ...],
    replacement: object,
) -> None:
    root = initialise_provenance_repo(tmp_path)
    worker = tmp_path / "artifacts" / "worker"
    worker.parent.mkdir()
    worker.write_bytes(b"worker")
    generated = run_provenance(root, "generate", "--worker", str(worker))
    assert generated.returncode == 0
    provenance_path = root / "release-provenance.json"
    recorded = json.loads(provenance_path.read_text())
    target = recorded
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement
    provenance_path.write_text(json.dumps(recorded, indent=2) + "\n")

    verified = run_provenance(
        root,
        "verify",
        "--worker",
        str(worker),
        "--provenance",
        str(provenance_path),
    )

    assert verified.returncode != 0


def qualification_response(provider: str, commit: str) -> str:
    names = (
        "worker (mathlib-free gate)",
        "NbDsl + kernel round-trip + e2e",
        "jupyterlab extension",
        "compatibility + external consumer",
    )
    return json.dumps([{
        "check_runs": [
            {
                "id": index,
                "name": name,
                "head_sha": commit,
                "status": "completed",
                "conclusion": "success",
                "app": {"slug": provider},
            }
            for index, name in enumerate(names, start=1)
        ],
    }])


@pytest.mark.parametrize(
    ("provider", "qualified"),
    (("github-actions", True), ("same-name-impostor", False)),
)
def test_release_qualification_requires_the_github_actions_provider(
    tmp_path: Path,
    provider: str,
    qualified: bool,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"${CHECK_RUNS_JSON:?}\"\n"
    )
    fake_gh.chmod(0o755)
    commit = "a" * 40
    completed = subprocess.run(
        [
            "bash",
            str(REPO / "scripts/require_release_qualification.sh"),
            "owner/repo",
            commit,
        ],
        capture_output=True,
        check=False,
        text=True,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "CHECK_RUNS_JSON": qualification_response(provider, commit),
        },
    )
    assert (completed.returncode == 0) is qualified, completed.stderr


def test_release_qualification_requires_the_governed_ci_workflow(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "case \"$*\" in\n"
        "  *actions/workflows/ci.yml/runs*) "
        "printf '%s\\n' '{\"workflow_runs\":[]}' ;;\n"
        "  *) printf '%s\\n' \"${CHECK_RUNS_JSON:?}\" ;;\n"
        "esac\n"
    )
    fake_gh.chmod(0o755)
    commit = "a" * 40

    completed = subprocess.run(
        [
            "bash",
            str(REPO / "scripts/require_release_qualification.sh"),
            "owner/repo",
            commit,
        ],
        capture_output=True,
        check=False,
        text=True,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "CHECK_RUNS_JSON": qualification_response(
                "github-actions",
                commit,
            ),
        },
    )

    assert completed.returncode != 0


def test_qualification_rejects_malformed_candidate_before_clone(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    invoked = tmp_path / "git-invoked"
    fake_git = fake_bin / "git"
    fake_git.write_text(
        "#!/usr/bin/env bash\n"
        f"touch {invoked}\n"
        "exit 99\n"
    )
    fake_git.chmod(0o755)

    completed = subprocess.run(
        [
            "bash",
            str(REPO / "scripts/qualify_consumer.sh"),
            "not-a-commit",
            str(tmp_path / "qualification"),
        ],
        capture_output=True,
        check=False,
        text=True,
        env={
            **os.environ,
            "AI_REVIEW_CI_SHA": "a" * 40,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
        },
    )

    assert completed.returncode != 0
    assert not invoked.exists()


def test_pr_body_toc_matches_top_level_headings() -> None:
    lines = (REPO / ".pr/PR_BODY.md").read_text().splitlines()
    contents_start = lines.index("## Contents") + 1
    contents_end = next(
        index for index in range(contents_start, len(lines))
        if lines[index].startswith("## ")
    )
    listed = [
        line.removeprefix("- ")
        for line in lines[contents_start:contents_end]
        if line.startswith("- ")
    ]
    headings = [
        line.removeprefix("## ")
        for line in lines[contents_end:]
        if line.startswith("## ")
    ]

    assert listed == headings


def test_frontend_python_floor_can_resolve_its_build_requirements() -> None:
    frontend = tomllib.loads(
        (REPO / "jupyterlab_nbdsl/pyproject.toml").read_text()
    )

    assert frontend["project"]["requires-python"] == ">=3.10"


def test_frontend_clean_preserves_importable_projected_version(
    tmp_path: Path,
) -> None:
    frontend = tmp_path / "frontend"
    package = frontend / "jupyterlab_nbdsl"
    package.mkdir(parents=True)
    shutil.copy2(REPO / "jupyterlab_nbdsl/package.json", frontend)
    shutil.copy2(
        REPO / "jupyterlab_nbdsl/jupyterlab_nbdsl/__init__.py",
        package,
    )
    (package / "_version.py").write_text('__version__ = "1.1.0"\n')
    clean_command = json.loads(
        (frontend / "package.json").read_text()
    )["scripts"]["clean"]

    cleaned = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", clean_command],
        cwd=frontend,
        capture_output=True,
        check=False,
        text=True,
    )
    assert cleaned.returncode == 0, cleaned.stdout + cleaned.stderr
    imported = subprocess.run(
        [
            sys.executable,
            "-c",
            "import jupyterlab_nbdsl; print(jupyterlab_nbdsl.__version__)",
        ],
        cwd=frontend,
        capture_output=True,
        check=False,
        text=True,
        env={**os.environ, "PYTHONPATH": str(frontend)},
    )
    assert imported.returncode == 0, imported.stderr
    assert imported.stdout.strip() == "1.1.0"
