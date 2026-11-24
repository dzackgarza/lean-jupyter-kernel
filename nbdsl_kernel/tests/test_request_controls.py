"""Adapter control laws using the real request router and explicit transport traces.

These checks do not claim native worker, engine, or notebook lifecycle acceptance.
"""

from __future__ import annotations

import os
import unittest
from collections import deque
from typing import cast

from nbdsl_kernel.protocol import CancelReply, CommitStatusReply, InspectOk
from nbdsl_kernel.worker import (
    WorkerClient, WorkerDied, WorkerInterrupted, WorkerUnavailable, WireProtocolError,
)
from nbdsl_kernel.worker.frames import FrameReader, RawFrame
from nbdsl_kernel.worker.errors import RequestRejected

NONCE = "request-control-worker"
PROFILE = "a" * 64


def response(rid: str, **fields: object) -> RawFrame:
    return {"worker_nonce": NONCE, "request_id": rid, **fields}


def receipt(**fields: object) -> RawFrame:
    return {"transaction_id": "actual-transaction", "output_batch_id": "actual-batch",
            "profile_sha256": PROFILE, "result_refs": ["actual-result"], **fields}


def executed(rid: str = "r1", **fields: object) -> RawFrame:
    return response(rid, **{"status": "ok", "parent_snapshot": "0", "snapshot": "1",
                            "commit": receipt(), "outputs": [], **fields})


class ReplyTrace:
    def __init__(self, frames: list[RawFrame | BaseException]) -> None:
        self.frames = deque(frames)

    def read_frame(self, timeout: float, process_pid: int) -> RawFrame:
        assert timeout > 0 and process_pid == os.getpid()
        frame = self.frames.popleft()
        if isinstance(frame, BaseException):
            raise frame
        return frame


class ControlledClient(WorkerClient):
    def __init__(self, frames: list[RawFrame | BaseException]) -> None:
        super().__init__("/unused-control-project", prelude="Init")
        self.worker_nonce = NONCE
        self.profile_sha256 = PROFILE
        self._protocol_ok = True
        self.worker_pid = os.getpid()
        self.replies = cast(FrameReader, ReplyTrace(frames))
        self.sent: list[RawFrame] = []
        self.streams: list[tuple[str, str]] = []
        self.on_stream = lambda name, text: self.streams.append((name, text))
        self.write_failure: BaseException | None = None

    def running(self) -> bool:
        return True

    def _write_frame(self, obj: RawFrame) -> None:
        self.require_session()
        self.sent.append(obj)
        failure, self.write_failure = self.write_failure, None
        if failure is not None:
            raise failure


class RequestControls(unittest.TestCase):
    def test_partial_send_blocks_more_source_until_exact_control(self) -> None:
        client = ControlledClient([response("r2", status="forced", invalidated_owners=["owner:7"])])
        client.write_failure = WorkerDied("request pipe closed after a partial frame")
        with self.assertRaises(WorkerUnavailable) as failed:
            client.execute("the original candidate")
        self.assertEqual(failed.exception.request_id, "r1")
        self.assertEqual(failed.exception.reason, "connection_lost_after_send")
        self.assertTrue(failed.exception.indeterminate)
        with self.assertRaises(WorkerUnavailable):
            client.execute("a later candidate")
        self.assertEqual(len(client.sent), 1)
        control = client.cancel("r1", "force")
        self.assertEqual(control.invalidated_owners, ["owner:7"])
        self.assertEqual([frame["op"] for frame in client.sent], ["execute", "cancel"])
        self.assertEqual(client.sent[-1]["mode"], "force")
        self.assertNotIn("code", client.sent[-1])
        self.assertEqual(client._uncertain, set())

    def test_late_execution_is_not_a_query_result_or_cached_payload(self) -> None:
        client = ControlledClient([
            TimeoutError("lost original reply"), executed(),
            response("r2", status="ok", found=False),
        ])
        with self.assertRaises(WorkerUnavailable):
            client.execute("original candidate")
        inspected = client.inspect("buffer", 2)
        self.assertIsInstance(inspected, InspectOk)
        self.assertFalse(inspected.found)
        self.assertEqual(client.snapshot, 0)
        self.assertEqual(client._pending, {})
        self.assertEqual(client._outstanding, set())
        self.assertEqual(client._uncertain, {"r1"})
        self.assertEqual([frame["op"] for frame in client.sent], ["execute", "inspect"])

    def test_visible_commit_status_resolves_only_its_target_without_display(self) -> None:
        client = ControlledClient([
            TimeoutError("lost reply"), response("r2", status="pending"),
            response("r3", status="committed", snapshot="1", commit=receipt()),
        ])
        with self.assertRaises(WorkerUnavailable):
            client.execute("original candidate")
        self.assertEqual(client.commit_status("r1", 0).status, "pending")
        with self.assertRaises(WorkerUnavailable):
            client.execute("blocked candidate")
        observed = client.commit_status("r1", 1)
        self.assertEqual(observed.status, "committed")
        self.assertEqual(client._uncertain, set())
        self.assertEqual(client.snapshot, 0)
        self.assertEqual(client.streams, [])
        self.assertEqual([frame["request_id"] for frame in client.sent], ["r1", "r2", "r3"])
        self.assertTrue(all("code" not in frame for frame in client.sent[1:]))

    def test_interrupt_is_cooperative_and_keeps_original_success(self) -> None:
        client = ControlledClient([
            KeyboardInterrupt(), executed(),
            response("r2", status="already_committed", snapshot="1", commit=receipt()),
        ])
        result = client.execute("one explicit candidate")
        self.assertEqual(result.status, "ok")
        self.assertEqual(client.snapshot, 1)
        self.assertEqual(client._pending, {})
        self.assertEqual(client.sent[-1]["mode"], "cooperative")
        self.assertEqual(client.sent[-1]["target_request_id"], "r1")
        self.assertEqual(len(client.sent), 2)

    def test_commit_ack_survives_lost_display_reply(self) -> None:
        client = ControlledClient([
            KeyboardInterrupt(),
            response("r2", status="already_committed", snapshot="1", commit=receipt()),
            TimeoutError("display reply missing"),
        ])
        with self.assertRaises(WorkerUnavailable) as failed:
            client.execute("one explicit candidate")
        self.assertEqual(failed.exception.reason, "commit_reply_unavailable")
        self.assertFalse(failed.exception.indeterminate)
        self.assertIsInstance(failed.exception.control, CancelReply)
        self.assertEqual(failed.exception.control.commit.model_dump(), receipt())
        self.assertEqual(client.snapshot, 1)
        self.assertEqual(client._uncertain, set())
        self.assertEqual(len(client.sent), 2)

    def test_original_commit_survives_a_lost_cancel_acknowledgement(self) -> None:
        client = ControlledClient([
            KeyboardInterrupt(), executed(), TimeoutError("cancel acknowledgement missing"),
        ])
        result = client.execute("one explicit candidate")
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.commit.model_dump(), receipt())
        self.assertEqual(client.snapshot, 1)
        self.assertEqual(client._uncertain, set())
        self.assertEqual(client._pending, {})
        self.assertEqual(client._outstanding, set())
        self.assertEqual(client._abandoned, {"r2"})
        self.assertEqual([frame["op"] for frame in client.sent], ["execute", "cancel"])

    def test_original_completion_cannot_change_acknowledged_commit(self) -> None:
        for original in (
            executed(snapshot="2"),
            executed(commit=receipt(output_batch_id="different-batch")),
            response("r1", status="cancelled", parent_snapshot="0", snapshot="0"),
        ):
            with self.subTest(original=original):
                client = ControlledClient([
                    KeyboardInterrupt(),
                    response("r2", status="already_committed", snapshot="1", commit=receipt()),
                    original,
                ])
                with self.assertRaises(WireProtocolError):
                    client.execute("one explicit candidate")
                self.assertEqual(client.snapshot, 1)
                self.assertFalse(client._protocol_ok)
                self.assertEqual(client._uncertain, {"r1"})
                self.assertEqual(client._pending, {})

    def test_cooperative_cancel_cannot_accept_implicit_force(self) -> None:
        client = ControlledClient([response("r1", status="forced", invalidated_owners=["owner:7"])])
        with self.assertRaises(WireProtocolError):
            client.cancel("original", "cooperative")
        self.assertFalse(client._protocol_ok)
        self.assertEqual(client.sent[0]["mode"], "cooperative")

    def test_cancel_ack_retains_draining_without_false_indeterminacy(self) -> None:
        client = ControlledClient([
            KeyboardInterrupt(), response("r2", status="cancelled"),
            TimeoutError("native frame still draining"),
        ])
        with self.assertRaises(WorkerUnavailable) as failed:
            client.execute("pending candidate")
        self.assertEqual(failed.exception.reason, "draining")
        self.assertFalse(failed.exception.indeterminate)
        self.assertEqual(client.snapshot, 0)
        self.assertEqual(client._uncertain, set())
        self.assertEqual(client.sent[-1]["mode"], "cooperative")

    def test_unacknowledged_cancel_does_not_force_or_claim_rollback(self) -> None:
        client = ControlledClient([KeyboardInterrupt(), TimeoutError("cancel acknowledgement missing")])
        with self.assertRaises(WorkerInterrupted) as failed:
            client.execute("pending candidate")
        self.assertEqual(failed.exception.reason, "cancel_unacknowledged")
        self.assertTrue(failed.exception.indeterminate)
        self.assertEqual(failed.exception.request_id, "r1")
        self.assertEqual(client._uncertain, {"r1"})
        self.assertEqual(client.sent[-1]["mode"], "cooperative")
        self.assertEqual(len(client.sent), 2)

    def test_not_found_control_does_not_hide_original_unavailable(self) -> None:
        client = ControlledClient([
            KeyboardInterrupt(), response("r1", status="unavailable", reason="snapshot_unavailable"),
            response("r2", status="not_found"),
        ])
        result = client.execute_at("original candidate", "cell", 19)
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.reason, "snapshot_unavailable")
        self.assertEqual(client.snapshot, 0)
        self.assertEqual(client._uncertain, set())

    def test_duplicate_diagnostic_never_settles_original(self) -> None:
        duplicate: RawFrame = {"op": "protocol_error", "worker_nonce": NONCE,
                               "offending_request_id": "r1", "reason": "duplicate_request_id"}
        client = ControlledClient([duplicate, executed()])
        self.assertEqual(client.execute("one candidate").status, "ok")
        self.assertEqual(len(client.sent), 1)
        self.assertEqual(client.streams, [("stderr", "duplicate request id: r1\n")])
        invalid = ControlledClient([{**duplicate, "outputs": []}])
        with self.assertRaises(WireProtocolError):
            invalid.execute("one candidate")

    def test_foreign_nonce_disables_later_source_transmission(self) -> None:
        client = ControlledClient([executed(worker_nonce="another-process")])
        with self.assertRaises(WireProtocolError):
            client.execute("original candidate")
        with self.assertRaises(WireProtocolError):
            client.complete("new buffer", 1)
        self.assertEqual(len(client.sent), 1)

    def test_every_receipt_keeps_frozen_profile(self) -> None:
        for operation in ("execute", "cancel", "commit_status"):
            with self.subTest(operation=operation):
                if operation == "execute":
                    raw = executed(commit=receipt(profile_sha256="b" * 64))
                else:
                    status = "already_committed" if operation == "cancel" else "committed"
                    raw = response("r1", status=status, snapshot="1",
                                   commit=receipt(profile_sha256="b" * 64))
                client = ControlledClient([raw])
                with self.assertRaises(WireProtocolError):
                    if operation == "execute":
                        client.execute("candidate")
                    elif operation == "cancel":
                        client.cancel("original")
                    else:
                        client.commit_status("original", 1)
                self.assertEqual(client.snapshot, 0)
                self.assertFalse(client._protocol_ok)

    def test_explicit_parent_and_failure_keep_exact_snapshot(self) -> None:
        client = ControlledClient([
            executed(parent_snapshot="12", snapshot="13"),
            response("r2", status="error", parent_snapshot="12", snapshot="12",
                     stratum="semanticAmbiguity", reason="original selections compete"),
        ])
        self.assertEqual(client.execute_at("first", "cell", 12).snapshot, 13)
        failed = client.execute_at("second", "cell", 12)
        self.assertEqual(failed.stratum, "semanticAmbiguity")
        self.assertEqual(client.snapshot, 12)
        self.assertEqual([frame["parent_snapshot"] for frame in client.sent], ["12", "12"])
        self.assertEqual([frame["request_id"] for frame in client.sent], ["r1", "r2"])

    def test_invalid_local_parent_never_transmits(self) -> None:
        for parent in (True, -1, 1.5, "01", None):
            with self.subTest(parent=parent):
                client = ControlledClient([])
                with self.assertRaises(WireProtocolError):
                    client.execute_at("candidate", "cell", parent)
                self.assertEqual(client.sent, [])

    def test_control_validation_rejects_invented_commit_or_force(self) -> None:
        from pydantic import ValidationError
        invalid = [
            (CancelReply, response("r1", status="cancelled", invalidated_owners=["unrelated"])),
            (CancelReply, response("r1", status="already_committed", snapshot="1")),
            (CommitStatusReply, response("r1", status="pending", commit=receipt())),
            (CommitStatusReply, response("r1", status="committed", snapshot="1")),
        ]
        for model, raw in invalid:
            with self.subTest(model=model, raw=raw), self.assertRaises(ValidationError):
                model.model_validate(raw)

    def test_invalid_framing_is_a_protocol_error_that_disables_source(self) -> None:
        for packet in (b"-1\n", b"unknown\n", b"2\n[]", b"1\n\xff", b"1\n{"):
            with self.subTest(packet=packet):
                read_fd, write_fd = os.pipe()
                try:
                    os.write(write_fd, packet)
                    client = ControlledClient([])
                    client.replies = FrameReader(read_fd)
                    with self.assertRaises(WireProtocolError) as failed:
                        client.execute("original candidate")
                    self.assertTrue(failed.exception.indeterminate)
                    self.assertEqual(failed.exception.request_id, "r1")
                    with self.assertRaises(WireProtocolError):
                        client.complete("later buffer", 1)
                    self.assertEqual(len(client.sent), 1)
                finally:
                    os.close(read_fd)
                    os.close(write_fd)

    def test_explicit_settlement_consumes_only_the_unread_original_reply(self) -> None:
        client = ControlledClient([TimeoutError("original wait expired"), executed()])
        with self.assertRaises(WorkerUnavailable):
            client.execute("original candidate")
        self.assertEqual(client.uncertain_executions, ("r1",))
        result = client.settle_execution("r1")
        self.assertEqual(result.status, "ok")
        self.assertEqual(client.snapshot, 1)
        self.assertEqual(client.uncertain_executions, ())
        self.assertEqual(client._execution_parents, {})
        self.assertEqual(len(client.sent), 1)

    def test_explicit_settlement_cannot_recover_a_discarded_late_batch(self) -> None:
        client = ControlledClient([
            TimeoutError("original wait expired"), executed(),
            response("r2", status="ok", found=False),
        ])
        with self.assertRaises(WorkerUnavailable):
            client.execute("original candidate")
        client.inspect("buffer", 1)
        with self.assertRaises(WorkerUnavailable) as failed:
            client.settle_execution("r1")
        self.assertEqual(failed.exception.reason, "receipt_unavailable")
        self.assertEqual(client.snapshot, 0)
        self.assertEqual(client._pending, {})
        self.assertEqual(len(client.sent), 2)

    def test_exact_rejection_is_consumed_without_disabling_the_session(self) -> None:
        rejection: RawFrame = {"op": "protocol_error", "worker_nonce": NONCE,
                               "offending_request_id": "r1", "reason": "invalid_execute"}
        client = ControlledClient([rejection, executed("r2")])
        with self.assertRaises(RequestRejected) as rejected:
            client.execute("rejected candidate")
        self.assertEqual(rejected.exception.request_id, "r1")
        self.assertTrue(client._protocol_ok)
        self.assertEqual(client.uncertain_executions, ())
        self.assertEqual(client.execute("explicit new candidate").status, "ok")
        self.assertEqual([frame["request_id"] for frame in client.sent], ["r1", "r2"])

    def test_original_rejection_survives_lost_cancel_ack(self) -> None:
        rejection: RawFrame = {"op": "protocol_error", "worker_nonce": NONCE,
                               "offending_request_id": "r1", "reason": "invalid_execute"}
        client = ControlledClient([KeyboardInterrupt(), rejection, TimeoutError("lost cancel ack")])
        with self.assertRaises(RequestRejected):
            client.execute("rejected candidate")
        self.assertEqual(client.uncertain_executions, ())
        self.assertTrue(client._protocol_ok)
        self.assertEqual(len(client.sent), 2)

    def test_existing_cancel_api_uses_validated_control_without_source(self) -> None:
        client = ControlledClient([
            response("r1", status="already_committed", snapshot="1", commit=receipt()),
        ])
        result = client.cancel_request("original")
        self.assertEqual(result["snapshot"], "1")
        self.assertEqual(result["commit"], receipt())
        self.assertEqual(client.sent[0]["mode"], "cooperative")
        self.assertNotIn("code", client.sent[0])


if __name__ == "__main__":
    unittest.main()
