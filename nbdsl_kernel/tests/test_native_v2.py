"""Independent raw-wire controls of the built notebook worker.

No production adapter, mock interpreter, or mathematical answer is supplied.
The Worker.Cell prelude permits checking the actual immutable observation
extension without provisioning Mathlib.
"""
from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import time
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Iterator

import pytest

ROOT = Path(__file__).resolve().parents[2] / "worker"
FEATURES = {
    "cas-session/2", "explicit-parent/2", "atomic-cell/2",
    "inspect-environment/2", "complete-environment/2", "cancel-by-request/2",
    "no-replay/2", "no-session-cache/2",
}


@lru_cache(maxsize=1)
def project_environment() -> dict[str, str]:
    """Capture the fixed build environment, not any worker/session state.

    The raw-wire deadline measures the actual worker, not repeated Lake
    workspace discovery. Each test starts an independently negotiated
    process and retains its original deadline.
    """
    raw = subprocess.check_output(["lake", "env", "env", "-0"], cwd=ROOT)
    return dict(
        os.fsdecode(item).split("=", 1)
        for item in raw.split(bytes([0])) if b"=" in item
    )


class Wire:
    def __init__(self) -> None:
        env = project_environment()
        req_r, self.req = os.pipe()
        self.rep, rep_w = os.pipe()
        try:
            self.proc = subprocess.Popen(
                [str(ROOT / ".lake/build/bin/nbdsl_worker"),
                 "--req-fd", str(req_r), "--rep-fd", str(rep_w),
                 "--prelude-module", "Worker.Cell"],
                cwd=ROOT, env=env, pass_fds=(req_r, rep_w),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except BaseException:
            os.close(self.req)
            os.close(self.rep)
            raise
        finally:
            os.close(req_r)
            os.close(rep_w)

    def send(self, frame: dict) -> None:
        payload = json.dumps(frame, ensure_ascii=False).encode("utf-8")
        data = memoryview(str(len(payload)).encode("ascii") + b"\n" + payload)
        while data:
            data = data[os.write(self.req, data):]

    def read(self) -> dict:
        deadline = time.monotonic() + 30

        def exact(count: int) -> bytes:
            data = bytearray()
            while len(data) < count:
                remaining = deadline - time.monotonic()
                assert remaining > 0 and select.select([self.rep], [], [], remaining)[0], (
                    "native control timeout", self.proc.pid, self.proc.poll())
                part = os.read(self.rep, count - len(data))
                assert part, ("unexpected EOF", self.proc.poll())
                data.extend(part)
            return bytes(data)

        header = bytearray()
        while not header.endswith(b"\n"):
            header.extend(exact(1))
        return json.loads(exact(int(header)))

    def negotiate(self) -> None:
        self.ready = self.read()
        assert self.ready["protocol"] == 2 and self.ready["snapshot"] == "0"
        assert FEATURES.issubset(self.ready["features"])
        self.nonce = self.ready["worker_nonce"]
        hello = {"op": "hello", "protocol": 2, "worker_nonce": self.nonce,
                 "session_policy": "cas_no_replay"}
        self.send(hello)
        assert self.read() == {**hello, "status": "ok"}

    def request(self, rid: str, op: str, **fields: object) -> None:
        self.send({"op": op, "protocol": 2, "worker_nonce": self.nonce,
                   "request_id": rid, **fields})

    def execute(self, rid: str, parent: str, code: str) -> dict:
        self.request(rid, "execute", cell_id=rid, parent_snapshot=parent,
                     session_policy="cas_no_replay", code=code)
        result = self.read()
        assert result["request_id"] == rid, result
        return result

    def inspect(self, rid: str, snapshot: str, name: str) -> dict:
        self.request(rid, "inspect", mode="environment", snapshot=snapshot,
                     code=name, cursor=0, detail_level=0)
        result = self.read()
        assert result["request_id"] == rid, result
        return result

    def close_input(self) -> None:
        if self.req >= 0:
            os.close(self.req)
            self.req = -1

    def finish(self) -> None:
        self.close_input()
        status = self.proc.wait(timeout=30)
        out, err = self.proc.communicate()
        assert status == 0, (status, out.decode(), err.decode())

    def close(self) -> None:
        self.close_input()
        if self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGKILL)
            self.proc.wait(timeout=5)
        os.close(self.rep)
        self.proc.communicate()


@contextmanager
def worker() -> Iterator[Wire]:
    wire = Wire()
    try:
        wire.negotiate()
        yield wire
    finally:
        wire.close()


def duplicate(wire: Wire, rid: str) -> dict:
    return {"op": "protocol_error", "worker_nonce": wire.nonce,
            "offending_request_id": rid, "reason": "duplicate_request_id"}


def test_exact_identity_and_branch() -> None:
    with worker() as w:
        # An invalid operation consumes its ID, a foreign nonce does not.
        w.request("malformed", "execute", code="def never := 1")
        bad = w.read()
        assert bad["op"] == "protocol_error", bad
        w.request("malformed", "describe")
        assert w.read() == duplicate(w, "malformed")
        w.request("parent", "describe", worker_nonce="other-worker")
        foreign = w.read()
        assert foreign["op"] == "protocol_error", foreign

        code = "def original : Nat := 41"
        original = w.execute("parent", "0", code)
        assert original["status"] == "ok", original
        parent = original["snapshot"]
        assert parent != "0" and original["commit"]["transaction_id"]
        for different in (code, "def changed : Nat := 42"):
            w.request("parent", "execute", cell_id="repeat", parent_snapshot="0",
                      session_policy="cas_no_replay", code=different)
            assert w.read() == duplicate(w, "parent")
        w.request("parent", "inspect", mode="environment", snapshot=parent,
                  code="original", cursor=0, detail_level=0)
        assert w.read() == duplicate(w, "parent")
        assert not w.inspect("absent", parent, "changed")["found"]
        assert w.inspect("visible", parent, "original")["found"]

        # Both new branches are explicit, and failure publishes nothing.
        a = w.execute("a", parent, "def branchA := original + 1")
        b = w.execute("b", parent, "def branchB := original + 2")
        assert a["status"] == b["status"] == "ok" and a["snapshot"] != b["snapshot"]
        assert w.inspect("has-a", a["snapshot"], "branchA")["found"]
        assert not w.inspect("no-a", b["snapshot"], "branchA")["found"]
        failed = w.execute("failure", a["snapshot"],
                           'def temporary := branchA\ndef broken : Nat := "bad"')
        assert failed["status"] == "error" and failed["snapshot"] == a["snapshot"]
        assert failed["outputs"] == [] and "commit" not in failed
        assert not w.inspect("no-temporary", a["snapshot"], "temporary")["found"]

        for rid, snapshot, expected in (
            ("own-receipt", a["snapshot"], "committed"),
            ("other-branch", b["snapshot"], "unavailable"),
        ):
            w.request(rid, "commit_status", snapshot=snapshot, target_request_id="a")
            result = w.read()
            assert result["status"] == expected, result
            if expected == "committed":
                assert result["commit"] == a["commit"]
        w.request("late-cancel", "cancel", target_request_id="a", mode="cooperative")
        late = w.read()
        assert late["status"] == "already_committed" and late["commit"] == a["commit"]


def test_duplicate_does_not_settle_pending_execution() -> None:
    with worker() as w:
        # The reader admits both frames while the evaluator is occupied.
        code = "#eval IO.sleep 1000\ndef actual := 7"
        for candidate in (code, "def impostor := 9"):
            w.request("once", "execute", cell_id="same", parent_snapshot="0",
                      session_policy="cas_no_replay", code=candidate)
        w.request("once", "describe")
        frames = [w.read() for _ in range(3)]
        assert frames.count(duplicate(w, "once")) == 2, frames
        execution, = [f for f in frames if f.get("request_id") == "once"]
        assert execution["status"] == "ok", execution
        assert w.inspect("actual", execution["snapshot"], "actual")["found"]
        assert not w.inspect("impostor", execution["snapshot"], "impostor")["found"]
        rerun = w.execute("explicit-rerun", "0", code)
        assert rerun["status"] == "ok"
        assert rerun["commit"] != execution["commit"]


def test_retained_observation_shadow_and_query_inertness() -> None:
    with worker() as w:
        first = ('run_cmd Lean.Elab.Command.liftCoreM <| Worker.Cell.setObservations '
                 '#[{ name := "R", type := "Nat" }]')
        second = ('run_cmd Lean.Elab.Command.liftCoreM <| Worker.Cell.setObservations '
                  '#[{ name := "R", type := "Nat" }, { name := "R", type := "Bool" }]')
        a = w.execute("old", "0", first)
        b = w.execute("shadow", a["snapshot"], second)
        assert a["status"] == b["status"] == "ok"
        assert w.inspect("old-view", a["snapshot"], "R")["type"] == "Nat"
        assert w.inspect("new-view", b["snapshot"], "R")["type"] == "Bool"
        # These candidate buffers are not commands to evaluate.
        candidate = "def forbidden := 7"
        w.request("syntax", "is_complete", mode="syntax", snapshot=b["snapshot"], code=candidate)
        assert w.read()["status"] == "ok"
        w.request("complete", "complete", mode="environment", snapshot=b["snapshot"],
                  code=candidate, cursor=len(candidate))
        assert w.read()["status"] == "ok"
        assert not w.inspect("not-executed", b["snapshot"], "forbidden")["found"]


@pytest.mark.parametrize("shutdown", [False, True])
def test_close_cancels_pending_work(shutdown: bool) -> None:
    with worker() as w:
        slow = ("set_option maxHeartbeats 0 in\nexample : True := by\n"
                + "".join(f"  have h{i} : Nat := {i}\n" for i in range(5000))
                + "  trivial")
        w.request("pending", "execute", cell_id="pending", parent_snapshot="0",
                  session_policy="cas_no_replay", code=slow)
        if shutdown:
            w.request("stop", "shutdown")
        else:
            w.close_input()
        replies = [w.read() for _ in range(2 if shutdown else 1)]
        original, = [f for f in replies if f["request_id"] == "pending"]
        assert original["status"] == "cancelled" and original["snapshot"] == "0", original
        assert original["outputs"] == [] and "commit" not in original, original
        if shutdown:
            assert any(f.get("request_id") == "stop" and f["status"] == "ok" for f in replies)
        w.finish()
