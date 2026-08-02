"""Locate the built ``nbdsl_worker`` and capture ``lake env`` bindings."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .errors import WorkerDied


def lake_env(project_root: Path) -> dict[str, str]:
    """Environment `lake env` would establish, without keeping lake as parent."""
    out = subprocess.check_output(
        ["lake", "env", "printenv"], cwd=project_root, text=True)
    env: dict[str, str] = {}
    for line in out.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            env[key] = value
    if not env:
        raise WorkerDied(f"lake env printenv produced no bindings in {project_root}")
    return env


def find_worker_exe(project_root: str | Path) -> Path | None:
    """The built worker binary for a Lean project — in its own build tree, or
    in a dependency's (git deps live under .lake/packages, one level deeper
    when the require names a subDir package; path deps build in place at the
    directory the Lake manifest records). Manifested path dependencies take
    precedence over stale package-cache candidates, so an exact local
    qualification cannot launch an older cached worker. None if not built."""
    root = Path(project_root)
    path_candidates: list[Path] = []
    manifest = root / "lake-manifest.json"
    if manifest.exists():
        for pkg in json.loads(manifest.read_text()).get("packages", []):
            if (pkg.get("type") == "path"
                    and pkg.get("name", "").strip("«»") == "nbdsl-worker"
                    and pkg.get("dir")):
                path_candidates.append(
                    (root / pkg.get("dir", ".")).resolve()
                    / ".lake/build/bin/nbdsl_worker")
    if path_candidates:
        # A manifested path dependency is authoritative. Falling through to
        # .lake/packages when its executable is absent can launch stale code.
        return next((c for c in path_candidates if c.exists()), None)
    candidates: list[Path] = [
        root / ".lake/build/bin/nbdsl_worker",
        *root.glob(".lake/packages/*/.lake/build/bin/nbdsl_worker"),
        *root.glob(".lake/packages/*/*/.lake/build/bin/nbdsl_worker"),
    ]
    return next((c for c in candidates if c.exists()), None)
