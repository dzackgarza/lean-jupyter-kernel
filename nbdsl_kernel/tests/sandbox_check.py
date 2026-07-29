#!/usr/bin/env python3
"""Sandbox check: with NBDSL_SANDBOX=1 the worker runs under bubblewrap —
it cannot write the project tree, while elaboration and /tmp still work.
Uses the production WorkerClient (the exact spawn path the kernel uses).

Run: python nbdsl_kernel/tests/sandbox_check.py   (after `just build`; needs bwrap)
"""

import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "nbdsl_kernel"))

if shutil.which("bwrap") is None:
    # Hard dependency of this proof: without it nothing is verified, so fail
    # loudly instead of letting the caller's pipeline read green.
    print("FAIL: bwrap is required to verify the sandbox", file=sys.stderr)
    sys.exit(1)

os.environ["NBDSL_SANDBOX"] = "1"
from nbdsl_kernel.worker import WorkerClient  # noqa: E402


def infos(rep):
    return [d for d in rep["diagnostics"] if d["severity"] == "information"]


def main():
    w = WorkerClient(REPO / "dsls/nbdsl")
    w.start()

    rep = w.execute('#eval IO.FS.writeFile "pwned.txt" "x"')
    assert rep["status"] == "error", rep
    assert not (REPO / "dsls/nbdsl" / "pwned.txt").exists()
    print("ok: project tree is read-only inside the sandbox")

    rep = w.execute('#eval IO.FS.writeFile "/tmp/nbdsl-sbx.txt" "x"')
    assert rep["status"] == "ok", rep
    assert not Path("/tmp/nbdsl-sbx.txt").exists()  # private tmpfs, not host /tmp
    print("ok: /tmp is a private tmpfs")

    rep = w.execute("#eval 6 * 7")
    assert rep["status"] == "ok", rep
    assert any("42" in d["message"] for d in infos(rep)), rep
    print("ok: elaboration works sandboxed")

    w.shutdown()
    print("PASS: sandbox")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)
