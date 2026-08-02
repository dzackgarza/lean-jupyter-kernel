"""Worker adapter exceptions and wire-protocol gate."""

from __future__ import annotations

from ..protocol import WIRE_PROTOCOL, ReadyFrame

READY_TIMEOUT = 600.0  # first prelude import loads mathlib oleans
REPLY_TIMEOUT = 3600.0  # elaboration can legitimately be slow; interrupt kills
CACHE_RESTORE_TIMEOUT = 120.0  # Mathlib olean restore; product path
CANCEL_GRACE = 3.0  # cooperative-cancel window before the worker is killed


class WorkerDied(RuntimeError):
    pass


class WorkerInterrupted(WorkerDied):
    """The worker was killed because a Jupyter interrupt escalated past the
    cooperative-cancel grace window. Deliberate — recovery paths must never
    auto-restart on this, or an interrupted cell would be transparently
    re-executed."""


class WireProtocolError(RuntimeError):
    """The worker speaks an incompatible wire protocol version."""


def check_wire_protocol(ready: ReadyFrame) -> None:
    """Refuse a worker whose wire protocol the adapter does not speak."""
    if ready.protocol != WIRE_PROTOCOL:
        raise WireProtocolError(
            f"worker wire protocol {ready.protocol} is incompatible "
            f"with adapter wire protocol {WIRE_PROTOCOL}")
