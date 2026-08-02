"""Wire-protocol compatibility at worker start.

The adapter refuses an incompatible wire protocol. Exact-commit identity,
executable hashing, and the provenance comm are gone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nbdsl_kernel.protocol import WIRE_PROTOCOL, ReadyFrame
from nbdsl_kernel.worker import (
    WireProtocolError,
    WorkerClient,
    check_wire_protocol,
)

REPO = Path(__file__).resolve().parents[2]
WORKER = REPO / "worker"


def test_check_wire_protocol_refuses_mismatch() -> None:
    ready = ReadyFrame.model_validate({
        "op": "ready",
        "protocol": WIRE_PROTOCOL + 1,
        "lean": "4.32.0",
        "pid": 1,
        "snapshot": 0,
    })
    with pytest.raises(WireProtocolError, match="wire protocol"):
        check_wire_protocol(ready)


def test_check_wire_protocol_accepts_match() -> None:
    ready = ReadyFrame.model_validate({
        "op": "ready",
        "protocol": WIRE_PROTOCOL,
        "lean": "4.32.0",
        "pid": 1,
        "snapshot": 0,
    })
    check_wire_protocol(ready)


def test_live_worker_speaks_expected_wire_protocol() -> None:
    client = WorkerClient(WORKER, prelude="Init")
    try:
        ready = client.start()
        assert ready.protocol == WIRE_PROTOCOL
        assert ready.lean.startswith("4.")
    finally:
        client.shutdown()
