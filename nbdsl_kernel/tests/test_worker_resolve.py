"""find_worker_exe path-dependency resolution."""

from __future__ import annotations

import json
from pathlib import Path

from nbdsl_kernel.worker import find_worker_exe


def test_worker_resolution_prefers_manifested_path_dependency(
        tmp_path: Path) -> None:
    project = tmp_path / "consumer"
    active = tmp_path / "active-worker"
    stale = project / ".lake/packages/nbdsl-worker/worker"
    active_exe = active / ".lake/build/bin/nbdsl_worker"
    stale_exe = stale / ".lake/build/bin/nbdsl_worker"
    active_exe.parent.mkdir(parents=True)
    stale_exe.parent.mkdir(parents=True)
    active_exe.write_text("active")
    stale_exe.write_text("stale")
    (project / ".lake").mkdir(exist_ok=True)
    (project / "lake-manifest.json").write_text(json.dumps({
            "packages": [{"type": "path", "name": "«nbdsl-worker»",
                          "dir": "../active-worker"}],
    }))

    assert find_worker_exe(project) == active_exe


def test_worker_resolution_fails_closed_for_unbuilt_manifested_path_dependency(
    tmp_path: Path) -> None:
    project = tmp_path / "consumer"
    stale = project / ".lake/packages/nbdsl-worker/worker"
    stale_exe = stale / ".lake/build/bin/nbdsl_worker"
    stale_exe.parent.mkdir(parents=True)
    stale_exe.write_text("stale")
    (project / ".lake").mkdir(exist_ok=True)
    (project / "lake-manifest.json").write_text(json.dumps({
    "packages": [{"type": "path", "name": "«nbdsl-worker»",
                  "dir": "../active-worker"}],
    }))

    assert find_worker_exe(project) is None
