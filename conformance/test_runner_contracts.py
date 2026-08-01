from __future__ import annotations

import re
import runpy
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any, Callable, cast

import pytest

REPO = Path(__file__).resolve().parents[1]
REFERENCE_PROFILE = REPO / "conformance/nbdsl.toml"
RUNNER = REPO / "conformance/runner.py"
sys.path.insert(0, str(RUNNER.parent))

import runner  # noqa: E402


def test_profile_rejects_commit_outside_the_published_identity_forms(
        tmp_path: Path) -> None:
    profile_path = tmp_path / "invalid-commit.toml"
    profile_path.write_text(re.sub(
        r"(?m)^commit = .+$",
        f'commit = "{"A" * 40}"',
        REFERENCE_PROFILE.read_text(),
    ))

    with pytest.raises(runner.ProfileError):
        runner.load_profile(profile_path)


def test_malformed_toml_is_profile_error_with_parser_cause(
        tmp_path: Path) -> None:
    profile_path = tmp_path / "malformed.toml"
    profile_path.write_text("[profile\n")

    with pytest.raises(runner.ProfileError) as caught:
        runner.load_profile(profile_path)

    assert isinstance(caught.value.__cause__, tomllib.TOMLDecodeError)


def test_cli_classifies_malformed_toml_as_setup_error(tmp_path: Path) -> None:
    profile_path = tmp_path / "malformed.toml"
    profile_path.write_text("[profile\n")

    completed = subprocess.run(
        [sys.executable, str(RUNNER), str(profile_path)],
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2


def test_independent_frame_oracle_uses_external_project_worker(
        tmp_path: Path) -> None:
    isolated_root = tmp_path / "isolated-kernel"
    isolated_runner = isolated_root / "conformance/runner.py"
    isolated_runner.parent.mkdir(parents=True)
    shutil.copy2(RUNNER, isolated_runner)
    shutil.copy2(REPO / "release.toml", isolated_root / "release.toml")
    isolated_roundtrip = isolated_root / "nbdsl_kernel/tests/roundtrip.py"
    isolated_roundtrip.parent.mkdir(parents=True)
    shutil.copy2(REPO / "nbdsl_kernel/tests/roundtrip.py", isolated_roundtrip)

    external_project = tmp_path / "external-project"
    shutil.copytree(
        REPO / "worker",
        external_project,
        ignore=shutil.ignore_patterns(".lake"),
    )
    external_worker = (
        external_project
        / ".lake/packages/lean-jupyter-kernel/worker/.lake/build/bin"
        / "nbdsl_worker"
    )
    external_worker.parent.mkdir(parents=True)
    external_worker.hardlink_to(
        REPO / "worker/.lake/build/bin/nbdsl_worker")

    namespace = runpy.run_path(str(isolated_runner))
    independent_frame_check = cast(
        Callable[[Path, str, dict[str, Any]], dict[str, Any]],
        namespace["independent_frame_check"],
    )
    result = independent_frame_check(
        external_project,
        "Init",
        {
            "command": '#eval IO.println "999\\n{\\\"op\\\": \\\"ready\\\"}"',
            "marker": "999",
        },
    )

    assert result["ready_op"] == "ready"
    assert result["forged_request_id"] == "forge"
    assert result["forged_status"] == "ok"
    assert result["marker_inside_reply_payload"] is True
    assert result["following_request_id"] == "after-forge"
    assert result["worker_stdout"] == ""
    assert result["exit_code"] == 0


def test_malformed_observation_projection_fails_loudly() -> None:
    mime = "application/vnd.nbdsl.path+json"
    config = {
        "mimes": [mime, "text/plain"],
        "projection": ["object", "source", "target", "steps"],
    }
    reply = {"status": "ok"}
    valid = {
        "msg_type": "display_data",
        "content": {
            "data": {
                mime: {
                    "object": "G",
                    "source": "Groups",
                    "target": "Sets",
                    "steps": ["forget"],
                },
                "text/plain": "G via forget",
            },
        },
    }
    assert runner._read(reply, [valid], config)["present"] is True

    malformed = {
        **valid,
        "content": {
            "data": {
                mime: {
                    "object": "G",
                    "source": "Groups",
                    "target": "Sets",
                },
                "text/plain": "G via forget",
            },
        },
    }
    with pytest.raises(runner.ProfileError, match="steps"):
        runner._read(reply, [malformed], config)


def test_failed_replay_restore_fails_the_real_conformance_run(
    tmp_path: Path,
) -> None:
    profile = tmp_path / "nbdsl-invalid-restore.toml"
    profile.write_text(
        REFERENCE_PROFILE.read_text().replace(
            'restore = ["end"]',
            'restore = ["#check nbdslDefinitelyMissing"]',
            1,
        )
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            str(profile),
            "--source-dir",
            str(REPO),
        ],
        capture_output=True,
        check=False,
        text=True,
        timeout=600,
    )

    assert completed.returncode != 0
    assert "restore" in completed.stderr.lower()
