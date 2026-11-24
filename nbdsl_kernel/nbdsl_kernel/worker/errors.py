"""Worker adapter exceptions and wire-protocol gate."""

from __future__ import annotations

from ..protocol import (
    NOTEBOOK_FEATURES, WIRE_PROTOCOL, CancelReply, CommitStatusReply, ReadyFrame,
)

READY_TIMEOUT = 600.0  # first prelude import loads mathlib oleans
REPLY_TIMEOUT = 3600.0  # a missed reply never authorizes replay or force
CANCEL_GRACE = 3.0  # acknowledgement window; expiry never authorizes force


class WorkerDied(RuntimeError):
    pass


class WorkerUnavailable(WorkerDied):
    """A resource outcome with the exact transport identity and established control evidence."""

    def __init__(self, reason: str, message: str = "", *, request_id: str | None = None,
                 indeterminate: bool = False,
                 control: CancelReply | CommitStatusReply | None = None) -> None:
        self.reason = reason
        self.request_id = request_id
        self.indeterminate = indeterminate
        self.control = control
        identity = f" (request {request_id})" if request_id is not None else ""
        detail = f": {message}" if message else ""
        super().__init__(f"unavailable/{reason}{identity}{detail}")


class WorkerInterrupted(WorkerUnavailable):
    """Cooperative cancellation was not acknowledged; no forced close is implied."""


class WireProtocolError(RuntimeError):
    """The worker speaks an incompatible wire protocol version."""

    def __init__(self, message: str, *, request_id: str | None = None,
                 indeterminate: bool = False) -> None:
        self.request_id = request_id
        self.indeterminate = indeterminate
        super().__init__(message)


class RequestRejected(WireProtocolError):
    """An actual protocol rejection of this exact request, not an execution result."""


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
