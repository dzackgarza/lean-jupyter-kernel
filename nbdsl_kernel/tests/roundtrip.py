#!/usr/bin/env python3
"""Protocol round-trip check against the bare nbdsl worker (no Jupyter).

Proves the repo-owned contracts: framed JSON on dedicated inherited fds,
cell atomicity against Command.State snapshots, cross-cell state, protocol
isolation from user stdout, sorry reporting, and structured DSL outputs.
Grows with each worker milestone; doubles as the protocol spec by example.

Run: python nbdsl_kernel/tests/roundtrip.py   (after `just build`)
"""

import json
import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
NBDSL = REPO / "dsls/nbdsl"
TIMEOUT = 300.0  # first prelude import loads mathlib oleans; give it room


# The frame codec below deliberately DUPLICATES nbdsl_kernel/worker.py's:
# this script is an independent oracle for the wire protocol. Sharing the
# production codec would let a codec bug pass both sides unnoticed. Do not
# "deduplicate" this into an import.
def write_frame(fd: int, obj: dict) -> None:
    payload = json.dumps(obj).encode()
    frame = memoryview(str(len(payload)).encode() + b"\n" + payload)
    while frame:
        frame = frame[os.write(fd, frame):]


class FrameReader:
    def __init__(self, fd: int) -> None:
        self.fd = fd
        self.buf = b""

    def _fill(self, deadline_msg: str) -> None:
        ready, _, _ = select.select([self.fd], [], [], TIMEOUT)
        if not ready:
            raise TimeoutError(deadline_msg)
        chunk = os.read(self.fd, 65536)
        if not chunk:
            raise EOFError("reply channel closed")
        self.buf += chunk

    def read_frame(self) -> dict:
        while b"\n" not in self.buf:
            self._fill("timed out waiting for frame length")
        line, self.buf = self.buf.split(b"\n", 1)
        n = int(line)
        while len(self.buf) < n:
            self._fill("timed out waiting for frame payload")
        payload, self.buf = self.buf[:n], self.buf[n:]
        frame: dict = json.loads(payload)
        return frame


class Worker:
    def __init__(self, prelude: str = "NbDsl.Notebook") -> None:
        req_r, req_w = os.pipe()
        rep_r, rep_w = os.pipe()
        self.proc = subprocess.Popen(
            ["lake", "env", str(REPO / "worker/.lake/build/bin/nbdsl_worker"),
             "--req-fd", str(req_r), "--rep-fd", str(rep_w),
             "--prelude-module", prelude],
            cwd=NBDSL,
            pass_fds=(req_r, rep_w),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        os.close(req_r)
        os.close(rep_w)
        self.req_fd = req_w
        self.replies = FrameReader(rep_r)
        self._rid = 0
        self.snapshot = "0"
        self.nonce = ""

    def header(self, rid: str, op: str) -> dict:
        return {"op": op, "protocol": 2, "worker_nonce": self.nonce, "request_id": rid}

    def request(self, op: str, **fields: object) -> dict:
        self._rid += 1
        rid = f"r{self._rid}"
        if op in ("inspect", "complete", "is_complete"):
            fields = {"snapshot": self.snapshot,
                      "mode": "syntax" if op == "is_complete" else "environment", **fields}
            if op == "inspect":
                fields.setdefault("detail_level", 0)
        write_frame(self.req_fd, {**self.header(rid, op), **fields})
        rep = self.replies.read_frame()
        assert rep.get("request_id", rep.get("offending_request_id")) == rid, rep
        assert rep["worker_nonce"] == self.nonce, rep
        return rep

    def execute(self, code: str, parent: str | None = None) -> dict:
        actual = self.snapshot if parent is None else parent
        rep = self.request("execute", code=code, cell_id=f"cell{self._rid}",
                           parent_snapshot=actual, session_policy="cas_no_replay")
        assert rep["parent_snapshot"] == actual, rep
        if rep["status"] == "ok":
            assert rep["commit"]["profile_sha256"] == self.profile_sha256, rep
            assert rep["snapshot"] != actual, rep
            self.snapshot = rep["snapshot"]
        else:
            assert rep["snapshot"] == actual and rep["outputs"] == [] and "commit" not in rep, rep
        return rep

    def shutdown(self) -> tuple[int, bytes, bytes]:
        os.close(self.req_fd)
        rc = self.proc.wait(timeout=TIMEOUT)
        out, err = self.proc.communicate(timeout=5)
        return rc, out, err

    def close(self) -> None:
        """Terminate the owned process group after any failed assertion."""
        try:
            os.close(self.req_fd)
        except OSError:
            pass
        if self.proc.poll() is None:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            self.proc.wait(timeout=5)
        out, err = self.proc.communicate(timeout=5)
        if self.proc.returncode != 0 and err:
            sys.stderr.buffer.write(err)
        if self.proc.returncode != 0 and out:
            sys.stdout.buffer.write(out)


def errors(rep: dict) -> list[dict]:
    return [d for d in rep["diagnostics"] if d["severity"] == "error"]


def infos(rep: dict) -> list[dict]:
    return [d for d in rep["diagnostics"] if d["severity"] == "information"]


def main() -> None:
    w = Worker()
    try:
        _run(w)
    finally:
        w.close()

def _run(w: Worker) -> None:
    ready = w.replies.read_frame()
    assert ready["op"] == "ready" and ready["protocol"] == 2, ready
    assert ready["lean"].startswith("4.32"), ready
    w.nonce = ready["worker_nonce"]
    w.profile_sha256 = ready["realization_profile"]["sha256"]
    assert ready["snapshot"] == "0", ready
    hello = {"op": "hello", "protocol": 2, "worker_nonce": w.nonce,
             "session_policy": "cas_no_replay"}
    write_frame(w.req_fd, hello)
    assert w.replies.read_frame() == {**hello, "status": "ok"}
    print(f"ok: ready handshake (lean {ready['lean']})")

    rep = w.request("describe")
    assert rep["status"] == "ok" and rep["snapshot"] == "0", rep
    print("ok: describe round-trip, request_id echoed")

    rep = w.request("flux-capacitate")
    assert rep["op"] == "protocol_error" and rep["reason"] == "unknown_operation", rep
    print("ok: unknown op rejected without evaluation")

    # --- elaboration basics -------------------------------------------------
    rep = w.execute("#eval 1+1")
    assert rep["status"] == "ok" and rep["snapshot"] == "1", rep
    assert any("2" in d["message"] for d in infos(rep)), rep
    print("ok: #eval cell commits a snapshot and reports its info message")

    # Multi-command cells accumulate EVERY command's messages (regression:
    # elabCommandTopLevel resets the log per command; the frontend loop must
    # merge or only the last command's diagnostics survive).
    rep = w.execute("#eval 10\n#eval 20")
    joined = " ".join(d["message"] for d in infos(rep))
    assert "10" in joined and "20" in joined, rep
    print("ok: multi-command cell keeps every command's messages")

    # Failure isolation: an error cell must not advance the snapshot.
    before = w.request("describe")["snapshot"]
    rep = w.execute('def bad : Nat := "string"')
    assert rep["status"] == "error" and rep["snapshot"] == before, rep
    assert errors(rep), rep
    print("ok: error cell rolls back to parent snapshot")

    # Atomicity within one cell: first command succeeds, second fails.
    rep = w.execute('def alsoBad : Nat := 3\ndef nope : Nat := "s"')
    assert rep["status"] == "error", rep
    rep = w.execute("#check alsoBad")
    assert rep["status"] == "error", rep  # alsoBad must NOT exist
    print("ok: failed cell discards even its successful declarations")

    # Cross-cell state.
    rep = w.execute("def x : Nat := 41")
    assert rep["status"] == "ok", rep
    rep = w.execute("#eval x + 1")
    assert rep["status"] == "ok", rep
    assert any("42" in d["message"] for d in infos(rep)), rep
    print("ok: definitions persist across cells")

    # Scope state: dangling namespace persists without 'expected end'.
    rep = w.execute("namespace Foo\ndef y : Nat := 1")
    assert rep["status"] == "ok" and not errors(rep), rep
    rep = w.execute("end Foo\n#eval Foo.y")
    assert rep["status"] == "ok", rep
    print("ok: open namespace survives a cell boundary")

    # set_option persists.
    rep = w.execute("set_option pp.universes true")
    assert rep["status"] == "ok", rep
    rep = w.execute("#check id")
    assert rep["status"] == "ok", rep
    assert any(".{" in d["message"] for d in infos(rep)), rep
    print("ok: set_option persists across cells")
    rep = w.execute("set_option pp.universes false")
    assert rep["status"] == "ok", rep

    # Protocol isolation: user prints cannot forge a frame. (`#eval` captures
    # stdout into the message log, so the print arrives as an info diagnostic;
    # either way it can never reach the control fds.)
    rep = w.execute('#eval IO.println "999\\n{\\"op\\": \\"ready\\"}"')
    assert rep["status"] == "ok", rep
    assert any("999" in d["message"] for d in infos(rep)), rep
    print("ok: frame-shaped user print stayed off the control channel")

    # Unicode positions: error column after a unicode-heavy prefix is in
    # code points, matching Python string indexing with no conversion.
    code = "def 𝔽₂test : Nat := nonexistentIdent"
    rep = w.execute(code)
    assert rep["status"] == "error", rep
    col = errors(rep)[0]["start"]["column"]
    assert col == code.index("nonexistentIdent"), (col, rep)
    print("ok: diagnostic columns are Unicode code points")

    # Sorry reporting.
    rep = w.execute("example : 1 + 1 = 2 := by sorry")
    assert rep["status"] == "ok", rep
    assert rep["sorries"] and "1 + 1 = 2" in rep["sorries"][0]["goal"], rep
    print("ok: sorries reported with goals")
    rep = w.execute("example : 2 + 2 = 4 := by sorry\n#eval 0")
    assert rep["status"] == "ok" and rep["sorries"], rep
    print("ok: sorry survives a later command in the same cell")

    # do-block let: term-level `let x ← e` must not collide with the DSL
    # let command (the documented parser trap).
    rep = w.execute("def io : IO Nat := do\n  let v ← pure 41\n  return v + 1")
    assert rep["status"] == "ok" and not errors(rep), rep
    print("ok: do-block `let x ← e` unaffected by the DSL let command")

    # --- the DSL itself -----------------------------------------------------
    rep = w.execute("open NbDsl NbDsl.Std")
    assert rep["status"] == "ok", rep
    rep = w.execute("prefer groupsToSets")
    assert rep["status"] == "ok" and not errors(rep), rep
    rep = w.execute("let G := GrpCat.of PUnit ∈ Groups")
    assert rep["status"] == "ok" and not errors(rep), rep
    rep = w.execute("#home G")
    assert rep["status"] == "ok", rep
    assert any("Groups" in d["message"] for d in infos(rep)), rep
    # The declaration prepares its native type-head members at execution,
    # so G. offers GrpCat members without query-time whnf.
    rep = w.request("complete", code="G.o", cursor=3)
    assert rep["status"] == "ok" and "G.of" in rep["matches"], rep
    print("ok: dot completion reads the committed bundled-category members")
    rep = w.execute("#via G ∈ Sets")
    assert rep["status"] == "ok", rep
    bundles = [o["mime"] for o in rep["outputs"]]
    path = next((b for b in bundles if "application/vnd.nbdsl.path+json" in b), None)
    assert path is not None and "text/plain" in path, rep
    print("ok: DSL sequence (prefer / let / #home / #via) with structured output")

    # Parse failure after a rich-emitting prefix must not report that bundle
    # (issue #11). Snapshot isolation is already covered above.
    before = w.request("describe")["snapshot"]
    rep = w.execute("#via G ∈ Sets\ndef ( := )")
    assert rep["status"] == "error" and rep["snapshot"] == before, rep
    assert rep.get("outputs") == [], rep
    print("ok: parse-failed cell suppresses prefix display bundles")

    # Predicates as category methods: defined in the DSL, registered,
    # enumerable, and decidable on declared objects.
    rep = w.execute("predicate RTAbelian (G ∈ Groups) := ∀ a b : G, a * b = b * a")
    assert rep["status"] == "ok" and not errors(rep), rep
    rep = w.execute("#methods Groups")
    assert any("RTAbelian" in d["message"] for d in infos(rep)), rep
    rep = w.execute("example : RTAbelian G := by decide")  # PUnit group is abelian
    assert rep["status"] == "ok" and not errors(rep), rep
    print("ok: predicate command defines, registers, and decides on objects")

    # Registry participates in rollback: a prefer inside a failing cell must
    # not survive it (env-extension state is snapshot state).
    rep = w.execute('prefer groupsToSets\ndef zap : Nat := "s"')
    assert rep["status"] == "error", rep
    print("ok: registry mutation in a failed cell rolled back with it")

    # --- is_complete (fixed inert lexical classification) --------------------
    for code, expected in [
        ("def foo : Nat := 4", "complete"),
        ("def foo : Nat :=", "incomplete"),
        # Arbitrary parser extensions are not executed by completeness.
        ("example : True := by", "unknown"),
        ("def ( := )", "unknown"),
    ]:
        rep = w.request("is_complete", code=code)
        assert rep["status"] == "ok" and rep["result"] == expected, (code, rep)
    print("ok: syntax classification does not run the environment parser")

    # --- complete / inspect (env + open-namespace aware) --------------------
    code = "prefer groupsToS"
    rep = w.request("complete", code=code, cursor=len(code))
    assert rep["status"] == "ok", rep
    assert "groupsToSets" in rep["matches"], rep
    assert rep["cursor_start"] == code.index("groupsToS"), rep
    print("ok: completion resolves through open namespaces")

    code = "#home G"
    rep = w.request("inspect", code=code, cursor=code.index("G"))
    assert rep["status"] == "ok" and rep["found"], rep
    assert rep["name"] == "G" and "Object" in rep["type"], rep
    rep = w.request("inspect", code="groupsToSets", cursor=0)
    assert rep["found"] and rep["name"] == "NbDsl.Std.groupsToSets", rep
    assert "Underlying-set functor" in (rep.get("doc") or ""), rep
    print("ok: inspect resolves, types, and documents identifiers")

    # Type-aware dot completion: x : Nat → members of Nat.
    rep = w.request("complete", code="x.su", cursor=4)
    assert rep["status"] == "ok" and "x.succ" in rep["matches"], rep
    print("ok: dot completion via the head of the resolved type")

    # The unexecuted local is not present in the committed environment.
    code = "def flocal (nlocal : Nat) : Nat := nlocal + 1"
    rep = w.request("inspect", code=code, cursor=code.rindex("nlocal"))
    assert rep["status"] == "ok" and not rep["found"], rep
    rep = w.request("inspect", code="flocal", cursor=0)
    assert rep["status"] == "ok" and not rep["found"], rep
    print("ok: inspect does not elaborate a candidate buffer")

    # --- cooperative cancel -------------------------------------------------
    w._rid += 1
    rid = f"r{w._rid}"
    # Bounded flat elaboration: enough tactic steps to remain in flight while
    # keeping the independent protocol check from becoming a memory stress
    # test. Each step passes cancellation checkpoints.
    slow = ("set_option maxHeartbeats 0 in\nexample : True := by\n"
            + "".join(f"  have h{i} : Nat := {i}\n" for i in range(5000))
            + "  trivial")
    write_frame(w.req_fd, {**w.header(rid, "execute"), "cell_id": "slow",
        "parent_snapshot": w.snapshot, "session_policy": "cas_no_replay", "code": slow})
    time.sleep(0.5)
    w._rid += 1
    cancel_id = f"r{w._rid}"
    write_frame(w.req_fd, {**w.header(cancel_id, "cancel"),
        "target_request_id": rid, "mode": "cooperative"})
    t0 = time.monotonic()
    replies = {rep["request_id"]: rep for rep in
               (w.replies.read_frame(), w.replies.read_frame())}
    took = time.monotonic() - t0
    rep = replies[rid]
    assert rep["status"] == "cancelled", replies
    assert rep["snapshot"] == w.snapshot and "commit" not in rep and rep["outputs"] == [], rep
    assert replies[cancel_id]["status"] == "cancelled", replies
    assert took < 5, took
    before = w.request("describe")["snapshot"]
    rep = w.execute("#eval x + 1")
    assert rep["status"] == "ok" and rep["snapshot"] == str(int(before) + 1), rep
    print(f"ok: cooperative cancel ({took:.2f}s), state intact, worker alive")

    # --- shutdown -----------------------------------------------------------
    rc, out, err = w.shutdown()
    assert rc == 0, (rc, err.decode()[-2000:])
    assert out == b"", out  # control traffic never leaks onto stdout
    print("ok: clean EOF shutdown; stdout untouched by control traffic")

    print("PASS: roundtrip")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)
