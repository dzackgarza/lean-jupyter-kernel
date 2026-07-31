"""Hatchling build hook: the adapter's exact build identity.

Generates `nbdsl_kernel/_build_info.json` on every wheel and editable-wheel
build from the only two authoritative sources: the repository's `release.toml`
(the one authored compatibility contract) and git. Missing git identity is a
hard build failure — an adapter that cannot say what it was built from must
not exist. The file is gitignored, because a tracked file cannot truthfully
contain its own commit.

The worker generates the same identity through its lakefile's `buildCommit`
target; the adapter refuses to run cells against a worker that disagrees.
"""

from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

BUILD_INFO = "nbdsl_kernel/_build_info.json"


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"nbdsl-kernel: `git {' '.join(args)}` failed in {root} "
            f"(exit {proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout.strip()


class CustomBuildHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        root = Path(self.root)
        # The repository root is one level up — true for a source checkout and
        # for `pip install git+…#subdirectory=nbdsl_kernel`, which clones the
        # whole repository. A missing release.toml raises here, loudly.
        release = tomllib.loads((root.parent / "release.toml").read_text())
        (root / BUILD_INFO).write_text(json.dumps({
            "release": release["release"]["version"],
            "commit": _git(root, "rev-parse", "HEAD"),
            # Recorded, never a build failure: dev builds must run, and
            # release qualification is what rejects a dirty tree.
            "dirty": bool(_git(root, "status", "--porcelain")),
            "plugin_api": release["compat"]["plugin_api"],
            "wire": release["compat"]["wire_protocol"],
            "toolchain": release["toolchain"]["lean"],
            "mathlib": release["toolchain"]["mathlib"],
        }, indent=2) + "\n")
