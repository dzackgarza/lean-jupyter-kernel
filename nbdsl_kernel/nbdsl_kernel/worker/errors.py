"""Worker adapter exceptions and wire-protocol gate."""

from __future__ import annotations

from ..protocol import NOTEBOOK_FEATURES, WIRE_PROTOCOL, ReadyFrame

READY_TIMEOUT = 600.0  # first prelude import loads mathlib oleans
REPLY_TIMEOUT = 3600.0  # elaboration can legitimately be slow; interrupt kills
CACHE_RESTORE_TIMEOUT = 120.0  # Mathlib olean restore; product path
CANCEL_GRACE = 3.0  # acknowledgement window; expiry never authorizes force


class WorkerDied(RuntimeError):
    pass


class WorkerInterrupted(WorkerDied):
    """Cooperative cancellation was not acknowledged; execution is indeterminate."""


class WireProtocolError(RuntimeError):
    """The worker speaks an incompatible wire protocol version."""


def check_wire_protocol(ready: ReadyFrame, expected_profile: str | None = None) -> None:
    """Reject before serializing any candidate source."""
    if ready.protocol != WIRE_PROTOCOL:
        raise WireProtocolError(
            f"unavailable/incompatible_protocol: worker wire protocol {ready.protocol} "
            f"is incompatible with adapter wire protocol {WIRE_PROTOCOL}")
    if not ready.worker_nonce or not ready.release or ready.snapshot != 0:
        raise WireProtocolError("unavailable/incompatible_protocol: missing startup identity")
    if not NOTEBOOK_FEATURES.issubset(ready.features):
        raise WireProtocolError("unavailable/incompatible_protocol: missing notebook features")
    if ready.realization_profile is None:
        raise WireProtocolError("unavailable/incompatible_protocol: missing frozen profile")
    if expected_profile is not None and ready.realization_profile.sha256 != expected_profile:
        raise WireProtocolError("unavailable/incompatible_protocol: realization profile mismatch")
