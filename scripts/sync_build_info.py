#!/usr/bin/env python3
"""Refresh the adapter's build identity in the source tree.

`just build` runs this right after `lake build nbdsl_worker`. The worker
re-embeds its identity on every build, while an editable install keeps
whatever `nbdsl_kernel/_build_info.json` it was installed with — so rebuilding
one half alone leaves the pair one commit apart and the runtime comparison
refuses it, correctly but uselessly. Refreshing both together is what makes
`just build` produce a matched pair.

Wheel installs are untouched: they bake the identity at build time through the
same `_identity.write_build_info`, which is right — those are release
artifacts, not a working tree.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "nbdsl_kernel"))

from _identity import write_build_info  # noqa: E402

if __name__ == "__main__":
    print(f"adapter build identity: {write_build_info(REPO / 'nbdsl_kernel')}")
