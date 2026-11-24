"""Exact request controls for one negotiated native notebook process.

Only live exchanges retain undelivered replies. Abandoned IDs are source-free
transport metadata; neither their source nor a completed result is cached.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Literal

from pydantic import ValidationError

from ..protocol import (
    COMPLETE_REPLY, INSPECT_REPLY, IS_COMPLETE_REPLY, SESSION_POLICY, WIRE_PROTOCOL,
    CancelReply, CommitReceipt, CommitStatusReply, CompleteOk, ExecuteReply,
    InspectOk, IsCompleteOk, WorkerError,
)
from .errors import (
    CANCEL_GRACE, REPLY_TIMEOUT, RequestRejected, WorkerDied, WorkerInterrupted,
    WorkerUnavailable, WireProtocolError,
)
from .frames import FrameReader, RawFrame


class SessionRequests(ABC):
    replies: FrameReader | None
    worker_pid: int | None
    on_stream: Callable[[str, str], None]

    def __init__(self) -> None:
        self.snapshot = 0
        self.worker_nonce: str | None = None
        self.profile_sha256: str | None = None
        self._protocol_ok = False
        self._rid = 0
        self._pending: dict[str, RawFrame] = {}
        self._outstanding: set[str] = set()
        self._abandoned: set[str] = set()
        self._drained: set[str] = set()
        self._uncertain: set[str] = set()
        self._execution_parents: dict[str, int] = {}

    @abstractmethod
    def require_session(self) -> None:
        """Check the live owner and completed handshake before any transmission."""

    @abstractmethod
    def _write_frame(self, obj: RawFrame) -> None:
        """Write exactly one complete frame to that actual owner."""

    def _reset_requests(self, *, acknowledged: bool) -> None:
        self._protocol_ok = acknowledged
        self._rid = 0
        self._pending.clear()
        self._outstanding.clear()
        self._abandoned.clear()
        self._drained.clear()
        self._uncertain.clear()
        self._execution_parents.clear()

    @property
    def uncertain_executions(self) -> tuple[str, ...]:
        """Request identities only, with no retained source or result payload."""
        return tuple(sorted(self._uncertain))

    @staticmethod
    def _serial(value: int) -> str:
        if type(value) is not int or value < 0:
            raise WireProtocolError("snapshot must be a nonnegative integer serial")
        return str(value)

    def _protocol_failure(self, message: str, *, request_id: str | None = None,
                          indeterminate: bool = False) -> WireProtocolError:
        self._protocol_ok = False
        if indeterminate and request_id is not None:
            self._uncertain.add(request_id)
        return WireProtocolError(message, request_id=request_id, indeterminate=indeterminate)

    def _request(self, op: str, payload: RawFrame,
                 timeout: float = REPLY_TIMEOUT) -> RawFrame:
        self.require_session()
        if {"op", "protocol", "request_id", "worker_nonce"}.intersection(payload):
            raise WireProtocolError("request payload overwrites its session identity")
        if op == "execute" and self._uncertain:
            raise WorkerUnavailable(
                "indeterminate_execution", "resolve the original request with source-free controls",
                request_id=sorted(self._uncertain)[0], indeterminate=True)
        self._rid += 1
        rid = f"r{self._rid}"
        self._outstanding.add(rid)
        if op == "execute":
            self._execution_parents[rid] = int(str(payload["parent_snapshot"]))
        completed = False
        try:
            try:
                self._write_frame({"op": op, "protocol": WIRE_PROTOCOL,
                                   "worker_nonce": self.worker_nonce, "request_id": rid, **payload})
                result = self._await(rid, timeout)
            except KeyboardInterrupt:
                if op != "execute":
                    raise WorkerUnavailable("interrupted", request_id=rid) from None
                result = self._interrupt_execute(rid)
            except RequestRejected:
                self._execution_parents.pop(rid, None)
                self._uncertain.discard(rid)
                completed = True
                raise
            except WireProtocolError as error:
                raise self._protocol_failure(str(error), request_id=rid,
                                             indeterminate=op == "execute") from error
            except WorkerUnavailable:
                raise
            except (WorkerDied, OSError, TimeoutError) as error:
                if op == "execute":
                    self._uncertain.add(rid)
                raise WorkerUnavailable(
                    "connection_lost_after_send", str(error), request_id=rid,
                    indeterminate=op == "execute") from error
            completed = True
            return result
        finally:
            self._outstanding.discard(rid)
            self._pending.pop(rid, None)
            if not completed:
                self._abandoned.add(rid)

    def _interrupt_execute(self, target: str) -> RawFrame:
        self._uncertain.add(target)
        try:
            control = self.cancel(target, "cooperative", timeout=CANCEL_GRACE)
        except RequestRejected as error:
            if target in self._pending:
                return self._await(target, CANCEL_GRACE)
            raise WorkerInterrupted("cancel_unacknowledged", str(error),
                                    request_id=target, indeterminate=True) from error
        except WireProtocolError as error:
            raise self._protocol_failure(str(error), request_id=target, indeterminate=True) from error
        except (WorkerDied, OSError, TimeoutError, KeyboardInterrupt) as error:
            if target in self._pending:
                # The original execution may have completed while its later cancel
                # acknowledgement was lost. Validate that actual reply normally;
                # cancellation uncertainty cannot erase an already delivered commit.
                return self._await(target, CANCEL_GRACE)
            raise WorkerInterrupted("cancel_unacknowledged", "no force or resend was attempted",
                                    request_id=target, indeterminate=True) from error
        if control.status == "already_committed":
            assert control.snapshot is not None
            self.snapshot = control.snapshot
        try:
            result = self._await(target, CANCEL_GRACE)
        except RequestRejected:
            raise
        except WireProtocolError as error:
            raise self._protocol_failure(str(error), request_id=target,
                                         indeterminate=target in self._uncertain) from error
        except (WorkerDied, OSError, TimeoutError, KeyboardInterrupt) as error:
            if control.status == "already_committed":
                reason = "commit_reply_unavailable"
            elif control.status in {"cancelled", "forced"}:
                reason = "draining"
            else:
                reason = control.reason or "cancel_unacknowledged"
            raise WorkerUnavailable(reason, "the original execution reply was not received",
                                    request_id=target, indeterminate=target in self._uncertain,
                                    control=control) from error
        if control.status in {"already_committed", "cancelled"}:
            try:
                completion = ExecuteReply.model_validate(result)
            except ValidationError as error:
                raise self._protocol_failure("malformed original completion after cancellation",
                                             request_id=target, indeterminate=True) from error
            if control.status == "already_committed":
                agrees = (completion.status == "ok" and completion.snapshot == control.snapshot
                          and completion.commit == control.commit)
            else:
                agrees = completion.status == "cancelled"
            if not agrees:
                raise self._protocol_failure("original completion contradicts its cancellation control",
                                             request_id=target, indeterminate=True)
        return result

    def _await(self, rid: str, timeout: float) -> RawFrame:
        if rid in self._pending:
            result = self._pending.pop(rid)
            if result.get("op") == "protocol_error":
                self._execution_parents.pop(rid, None)
                self._uncertain.discard(rid)
                raise RequestRejected(str(result.get("reason")), request_id=rid)
            return result
        if self.replies is None or self.worker_pid is None:
            raise WorkerDied("the original worker reply channel is absent")
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("timed out waiting for worker reply")
            rep = self.replies.read_frame(remaining, self.worker_pid)
            if rep.get("worker_nonce") != self.worker_nonce:
                raise self._protocol_failure("reply belongs to another worker nonce")
            if rep.get("op") == "protocol_error":
                if rep.get("reason") == "duplicate_request_id":
                    if (set(rep) != {"op", "worker_nonce", "offending_request_id", "reason"}
                            or not isinstance(rep.get("offending_request_id"), str)):
                        raise self._protocol_failure("malformed duplicate-ID diagnostic")
                    self.on_stream("stderr", f"duplicate request id: {rep['offending_request_id']}\n")
                    continue
                if (set(rep) != {"op", "worker_nonce", "offending_request_id", "reason"}
                        or not isinstance(rep.get("reason"), str)):
                    raise self._protocol_failure("malformed exact-request rejection")
            key = (rep.get("offending_request_id") if rep.get("op") == "protocol_error"
                   else rep.get("request_id"))
            if not isinstance(key, str) or not key:
                raise self._protocol_failure("reply has no exact transport request ID")
            if key in self._abandoned:
                # Source-free control can resolve this request. A late display batch is
                # never retained, rebound to a query, or published as that query's reply.
                self._drained.add(key)
                continue
            if key not in self._outstanding or key in self._pending:
                raise self._protocol_failure("worker returned an unknown or repeated response")
            if key == rid:
                if rep.get("op") == "protocol_error":
                    self._execution_parents.pop(rid, None)
                    self._uncertain.discard(rid)
                    raise RequestRejected(str(rep.get("reason")), request_id=rid)
                return rep
            self._pending[key] = rep

    def _check_commit(self, receipt: CommitReceipt | None, rid: str | None,
                      *, indeterminate: bool = False) -> None:
        if receipt is not None and receipt.profile_sha256 != self.profile_sha256:
            raise self._protocol_failure("reply changed the frozen realization profile",
                                         request_id=rid, indeterminate=indeterminate)

    def execute(self, code: str, cell_id: str = "cell") -> ExecuteReply:
        return self.execute_at(code, cell_id, self.snapshot)

    def execute_at(self, code: str, cell_id: str, parent: int) -> ExecuteReply:
        parent_serial = self._serial(parent)
        raw = self._request("execute", {"code": code, "cell_id": cell_id,
                                      "session_policy": SESSION_POLICY,
                                      "parent_snapshot": parent_serial})
        rid = str(raw["request_id"])
        return self._accept_execution(rid, raw)

    def _accept_execution(self, rid: str, raw: RawFrame) -> ExecuteReply:
        parent = self._execution_parents.get(rid)
        if parent is None:
            raise self._protocol_failure("execution reply has no original parent", request_id=rid)
        try:
            result = ExecuteReply.model_validate(raw)
        except ValidationError as error:
            raise self._protocol_failure("malformed execution publication", request_id=rid,
                                         indeterminate=True) from error
        if result.parent_snapshot is not None and result.parent_snapshot != parent:
            raise self._protocol_failure("execution changed its selected parent", request_id=rid,
                                         indeterminate=True)
        self._check_commit(result.commit, rid, indeterminate=True)
        self._uncertain.discard(rid)
        self._execution_parents.pop(rid, None)
        if result.status in {"ok", "error", "cancelled"}:
            assert result.snapshot is not None
            self.snapshot = result.snapshot
        return result

    def settle_execution(self, target: str, timeout: float = REPLY_TIMEOUT) -> ExecuteReply:
        """Explicitly receive a still-unread original reply without resending source."""
        self.require_session()
        if target not in self._uncertain or target not in self._execution_parents:
            raise WireProtocolError("no such uncertain original execution")
        if target in self._drained:
            raise WorkerUnavailable("receipt_unavailable", "the late original reply was discarded; use commit_status",
                                    request_id=target, indeterminate=True)
        self._abandoned.discard(target)
        self._outstanding.add(target)
        completed = False
        try:
            raw = self._await(target, timeout)
            result = self._accept_execution(target, raw)
            completed = True
            return result
        except RequestRejected:
            self._execution_parents.pop(target, None)
            self._uncertain.discard(target)
            completed = True
            raise
        except WireProtocolError as error:
            raise self._protocol_failure(str(error), request_id=target, indeterminate=True) from error
        except (WorkerDied, OSError, TimeoutError, KeyboardInterrupt) as error:
            raise WorkerUnavailable("connection_lost_after_send", str(error),
                                    request_id=target, indeterminate=True) from error
        finally:
            self._outstanding.discard(target)
            self._pending.pop(target, None)
            if not completed:
                self._abandoned.add(target)

    def complete(self, code: str, cursor: int,
                 snapshot: int | None = None) -> CompleteOk | WorkerError:
        serial = self._serial(self.snapshot if snapshot is None else snapshot)
        return COMPLETE_REPLY.validate_python(self._request(
            "complete", {"mode": "environment", "snapshot": serial,
                         "code": code, "cursor": cursor}, timeout=30))

    def inspect(self, code: str, cursor: int, detail_level: int = 0,
                snapshot: int | None = None) -> InspectOk | WorkerError:
        serial = self._serial(self.snapshot if snapshot is None else snapshot)
        return INSPECT_REPLY.validate_python(self._request(
            "inspect", {"mode": "environment", "snapshot": serial,
                        "code": code, "cursor": cursor, "detail_level": detail_level}, timeout=30))

    def is_complete(self, code: str,
                    snapshot: int | None = None) -> IsCompleteOk | WorkerError:
        serial = self._serial(self.snapshot if snapshot is None else snapshot)
        return IS_COMPLETE_REPLY.validate_python(self._request(
            "is_complete", {"mode": "syntax", "snapshot": serial, "code": code}, timeout=30))

    def cancel(self, target: str, mode: Literal["cooperative", "force"] = "cooperative", *,
               timeout: float = REPLY_TIMEOUT) -> CancelReply:
        if not target or mode not in {"cooperative", "force"}:
            raise WireProtocolError("cancellation requires its exact target and explicit mode")
        raw = self._request("cancel", {"target_request_id": target, "mode": mode}, timeout)
        try:
            result = CancelReply.model_validate(raw)
        except ValidationError as error:
            raise self._protocol_failure("malformed cancellation acknowledgement") from error
        if result.target_request_id is not None and result.target_request_id != target:
            raise self._protocol_failure("cancellation acknowledged another request")
        if mode == "cooperative" and result.status == "forced":
            raise self._protocol_failure("cooperative cancellation forced native owners")
        self._check_commit(result.commit, result.request_id)
        if result.status in {"cancelled", "already_committed", "forced"}:
            self._uncertain.discard(target)
        return result

    def commit_status(self, target: str, snapshot: int) -> CommitStatusReply:
        if not target:
            raise WireProtocolError("commit status requires its exact target request")
        serial = self._serial(snapshot)
        raw = self._request("commit_status", {"target_request_id": target, "snapshot": serial}, 30)
        try:
            result = CommitStatusReply.model_validate(raw)
        except ValidationError as error:
            raise self._protocol_failure("malformed commit-status observation") from error
        if result.target_request_id is not None and result.target_request_id != target:
            raise self._protocol_failure("commit status answered another request")
        self._check_commit(result.commit, result.request_id)
        if result.status == "committed":
            self._uncertain.discard(target)
        return result

    def cancel_request(self, target: str, *, force: bool = False) -> RawFrame:
        """Keep the existing control API on the same validated, source-free exchange."""
        result = self.cancel(target, "force" if force else "cooperative", timeout=CANCEL_GRACE)
        raw: RawFrame = result.model_dump(exclude_none=True)
        if result.snapshot is not None:
            raw["snapshot"] = str(result.snapshot)
        return raw
