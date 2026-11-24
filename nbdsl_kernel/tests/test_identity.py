"""Wire-protocol compatibility at worker start.

The adapter refuses an incompatible wire protocol. Exact-commit identity,
executable hashing, and the provenance comm are gone.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError
from nbdsl_kernel.kernel import NbDslKernel
from nbdsl_kernel.protocol import WIRE_PROTOCOL, ReadyFrame
from nbdsl_kernel.worker import (
    WireProtocolError,
    WorkerClient,
    check_wire_protocol,
)

REPO = Path(__file__).resolve().parents[2]
WORKER = REPO / "worker"


def test_language_info_defaults_and_env_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No __init__: the property reads the kernelspec env, never instance state.
    k = object.__new__(NbDslKernel)
    assert k.language_info == {
        "name": "lean4",
        "mimetype": "text/x-lean4",
        "file_extension": ".lean",
    }
    monkeypatch.setenv("NBDSL_LANGUAGE_NAME", "casdsl")
    monkeypatch.setenv("NBDSL_MIMETYPE", "text/x-casdsl")
    monkeypatch.setenv("NBDSL_LANGUAGE_EXT", ".casdsl")
    assert k.language_info == {
        "name": "casdsl",
        "mimetype": "text/x-casdsl",
        "file_extension": ".casdsl",
    }


def test_check_wire_protocol_refuses_mismatch() -> None:
    ready = ReadyFrame.model_validate(
        {
            "op": "ready",
            "protocol": WIRE_PROTOCOL + 1,
            "lean": "4.32.0",
            "pid": 1,
            "snapshot": 0,
        }
    )
    with pytest.raises(WireProtocolError, match="wire protocol"):
        check_wire_protocol(ready)


def test_check_wire_protocol_accepts_match() -> None:
    ready = ReadyFrame.model_validate(
        {
            "op": "ready",
            "protocol": WIRE_PROTOCOL,
            "lean": "4.33.0",
            "pid": 1,
            "snapshot": "0",
            "release": "identity-control",
            "worker_nonce": "identity-control",
            "realization_profile": {"id": "all", "sha256": "0" * 64},
            "features": list(_NOTEBOOK_FEATURES),
        }
    )
    check_wire_protocol(ready)


def test_live_worker_speaks_expected_wire_protocol() -> None:
    client = WorkerClient(WORKER, prelude="Init")
    try:
        ready = client.start()
        assert ready.protocol == WIRE_PROTOCOL
        assert ready.lean.startswith("4.")
    finally:
        client.shutdown()


_NOTEBOOK_FEATURES = (
    "cas-session/2", "explicit-parent/2", "atomic-cell/2",
    "inspect-environment/2", "complete-environment/2", "cancel-by-request/2",
    "no-replay/2", "no-session-cache/2",
)


def test_v2_rejects_legacy_ready() -> None:
    """The actual protocol-1 shape cannot authorize candidate transmission."""
    with pytest.raises((WireProtocolError, ValidationError)):
        check_wire_protocol(ReadyFrame.model_validate({
            "op": "ready", "protocol": 1, "lean": "4.32.0",
            "pid": 1, "snapshot": 0,
        }))


@pytest.mark.parametrize("missing", _NOTEBOOK_FEATURES)
def test_v2_rejects_missing_notebook_feature(missing: str) -> None:
    """Version agreement alone never grants the eight notebook capabilities."""
    with pytest.raises((WireProtocolError, ValidationError)):
        check_wire_protocol(ReadyFrame.model_validate({
            "op": "ready", "protocol": WIRE_PROTOCOL, "lean": "4.33.0",
            "release": "identity-control", "pid": 1, "snapshot": "0",
            "worker_nonce": "identity-control",
            "realization_profile": {"id": "all", "sha256": "0" * 64},
            "features": [feature for feature in _NOTEBOOK_FEATURES if feature != missing],
        }))


@pytest.mark.parametrize("operation", ("inspect", "complete"))
def test_v2_query_first_does_not_start_or_transmit(
    monkeypatch: pytest.MonkeyPatch, operation: str,
) -> None:
    """Exercise the real Jupyter handlers while forbidding process/source effects."""
    kernel = object.__new__(NbDslKernel)
    kernel.worker = WorkerClient(WORKER, prelude="Init")
    kernel._started = False
    kernel._silent = False
    kernel._init_error = None
    effects: list[str] = []

    def forbidden(*args: object, **kwargs: object) -> None:
        effects.append("worker start or source transmission")
        raise AssertionError("an observation started/recovered a worker or transmitted source")

    monkeypatch.setattr(kernel, "_stream", lambda *args: None)
    for method in ("start", "restart_fresh", "restart_and_replay", "_write_frame"):
        monkeypatch.setattr(kernel.worker, method, forbidden)
    candidate = "Nat.succ"
    if operation == "inspect":
        reply = asyncio.run(kernel.do_inspect(candidate, 0))
    else:
        reply = asyncio.run(kernel.do_complete(candidate, len(candidate)))
    assert reply["status"] == "error", reply
    assert "worker_absent" in str(reply), reply
    assert effects == []
    assert kernel.worker.proc is None
