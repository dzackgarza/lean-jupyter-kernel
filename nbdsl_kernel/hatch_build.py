"""Hatchling build hook: the adapter's exact build identity.

Generates `nbdsl_kernel/_build_info.json` on every distribution build. A
source checkout derives it from Git and release.toml; a generated sdist
authenticates and propagates its embedded copy. The computation itself lives
in `_identity.py`, which `just build` also calls through
`scripts/sync_build_info.py` — one implementation, so a wheel and a refreshed
source tree can never disagree about what identity means.

The worker generates the same identity through its lakefile's `buildCommit`
target; the adapter refuses to run cells against a worker that disagrees.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

# The hook is loaded by path, so its own directory is not importable by
# default; `_identity` sits next to this file.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _identity import write_build_info  # noqa: E402


class CustomBuildHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        write_build_info(Path(self.root))
