from __future__ import annotations

import os
import signal
import time

import psutil
import pytest

import roundtrip


def _worker_descendants() -> dict[int, psutil.Process]:
    current = psutil.Process()
    return {
        child.pid: child
        for child in current.children(recursive=True)
        if "nbdsl_worker" in " ".join(child.cmdline())
    }


def test_roundtrip_startup_failure_terminates_owned_worker(
        monkeypatch: pytest.MonkeyPatch) -> None:
    before = _worker_descendants()
    monkeypatch.setattr(roundtrip, "TIMEOUT", 0.01)

    try:
        with pytest.raises(TimeoutError):
            roundtrip.main()
        leaked: dict[int, psutil.Process] = {}
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            leaked = {
                pid: proc
                for pid, proc in _worker_descendants().items()
                if pid not in before
            }
            if not leaked:
                break
            time.sleep(0.05)
        assert not leaked
    finally:
        for proc in _worker_descendants().values():
            try:
                os.kill(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
