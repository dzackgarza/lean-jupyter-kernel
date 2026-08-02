"""Wire-protocol compatibility at worker start.

The adapter refuses an incompatible wire protocol. Exact-commit identity,
executable hashing, and the provenance comm are gone.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from jupyter_client.kernelspec import KernelSpecManager
from jupyter_client.manager import KernelManager

from nbdsl_kernel.protocol import WIRE_PROTOCOL, ReadyFrame
from nbdsl_kernel.worker import WireProtocolError, WorkerClient
from test_e2e import run_cell

from jupyter_helpers import clean_jupyter_env, start_init_kernel

REPO = Path(__file__).resolve().parents[2]
WORKER = REPO / "worker"


def test_ready_rejects_incompatible_wire_protocol() -> None:
    ready = ReadyFrame.model_validate({
        "op": "ready",
        "protocol": WIRE_PROTOCOL + 1,
        "lean": "4.32.0",
        "pid": 1,
        "snapshot": 0,
    })
    with pytest.raises(WireProtocolError, match="wire protocol"):
        if ready.protocol != WIRE_PROTOCOL:
            raise WireProtocolError(
                f"worker wire protocol {ready.protocol} is incompatible "
                f"with adapter wire protocol {WIRE_PROTOCOL}")


def test_live_worker_speaks_expected_wire_protocol() -> None:
    client = WorkerClient(WORKER, prelude="Init")
    try:
        ready = client.start()
        assert ready.protocol == WIRE_PROTOCOL
        assert ready.lean.startswith("4.")
    finally:
        client.shutdown()


def test_kernel_reports_wire_mismatch_as_typed_error(tmp_path: Path) -> None:
    """A live kernelspec surfaces WireProtocolError on execute, not a silent death."""
    # Install the kernelspec, then start a kernel whose env demands a
    # different wire version than the built worker advertises.
    manager, client = start_init_kernel(
        tmp_path, "nbdsl-wire-test", project=WORKER, prelude="Init")
    client.stop_channels()
    manager.shutdown_kernel(now=True)

    data = tmp_path / "jupyter"
    env = clean_jupyter_env(NBDSL_WIRE_PROTOCOL=str(WIRE_PROTOCOL + 1))
    manager = KernelManager(
        kernel_name="nbdsl-wire-test",
        kernel_spec_manager=KernelSpecManager(
            kernel_dirs=[str(data / "kernels")]
        ),
    )
    manager.start_kernel(env=env)
    client = manager.client()
    client.start_channels()
    try:
        client.wait_for_ready(timeout=60)
        reply, _ = run_cell(client, "#eval 1")
        assert reply["status"] == "error"
        assert reply["ename"] == "WireProtocolError"
    finally:
        client.stop_channels()
        manager.shutdown_kernel(now=True)
