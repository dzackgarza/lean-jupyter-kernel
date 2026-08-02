#!/usr/bin/env python3
"""Run a command inside a finite, no-swap cgroup resource boundary."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "nbdsl_kernel"))

from nbdsl_kernel.resource_limits import main  # noqa: E402


raise SystemExit(main())
