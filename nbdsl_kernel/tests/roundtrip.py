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
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
NBDSL = REPO / "nbdsl"
TIMEOUT = 300.0  # first prelude import loads mathlib oleans; give it room


def write_frame(fd: int, obj: dict) -> None:
    payload = json.dumps(obj).encode()
    os.write(fd, str(len(payload)).encode() + b"\n" + payload)


class FrameReader:
    def __init__(self, fd: int):
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
        return json.loads(payload)


class Worker:
    def __init__(self, prelude="NbDsl.Notebook"):
        req_r, req_w = os.pipe()
        rep_r, rep_w = os.pipe()
        self.proc = subprocess.Popen(
            ["lake", "env", ".lake/build/bin/nbdsl_worker",
             "--req-fd", str(req_r), "--rep-fd", str(rep_w),
             "--prelude-module", prelude],
            cwd=NBDSL,
            pass_fds=(req_r, rep_w),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        os.close(req_r)
        os.close(rep_w)
        self.req_fd = req_w
        self.replies = FrameReader(rep_r)
        self._rid = 0

    def request(self, op, **fields) -> dict:
        self._rid += 1
        rid = f"r{self._rid}"
        write_frame(self.req_fd, {"op": op, "request_id": rid, **fields})
        rep = self.replies.read_frame()
        assert rep.get("request_id") == rid, rep
        return rep

    def execute(self, code, parent=None) -> dict:
        fields = {"code": code, "cell_id": f"cell{self._rid}"}
        if parent is not None:
            fields["parent_snapshot"] = parent
        return self.request("execute", **fields)

    def shutdown(self):
        os.close(self.req_fd)
        rc = self.proc.wait(timeout=TIMEOUT)
        out, err = self.proc.communicate(timeout=5)
        return rc, out, err


def errors(rep):
    return [d for d in rep["diagnostics"] if d["severity"] == "error"]


def infos(rep):
    return [d for d in rep["diagnostics"] if d["severity"] == "information"]


def main() -> None:
    w = Worker()

    ready = w.replies.read_frame()
    assert ready["op"] == "ready" and ready["protocol"] == 1, ready
    assert ready["lean"].startswith("4.32"), ready
    print(f"ok: ready handshake (lean {ready['lean']})")

    rep = w.request("describe")
    assert rep["status"] == "ok" and rep["snapshot"] == 0, rep
    print("ok: describe round-trip, request_id echoed")

    rep = w.request("flux-capacitate")
    assert rep["status"] == "unsupported", rep
    print("ok: unknown op reported unsupported (forward-compat seam)")

    # --- elaboration basics -------------------------------------------------
    rep = w.execute("#eval 1+1")
    assert rep["status"] == "ok" and rep["snapshot"] == 1, rep
    assert any("2" in d["message"] for d in infos(rep)), rep
    print("ok: #eval cell commits a snapshot and reports its info message")

    # Failure isolation: an error cell must not advance the snapshot.
    rep = w.execute('def bad : Nat := "string"')
    assert rep["status"] == "error" and rep["snapshot"] == 1, rep
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
    rep = w.execute("#via G ∈ Sets")
    assert rep["status"] == "ok", rep
    bundles = [o["data"] for o in rep["outputs"]]
    path = next((b for b in bundles if "application/vnd.nbdsl.path+json" in b), None)
    assert path is not None and "text/plain" in path, rep
    print("ok: DSL sequence (prefer / let / #home / #via) with structured output")

    # Registry participates in rollback: a prefer inside a failing cell must
    # not survive it (env-extension state is snapshot state).
    rep = w.execute('prefer groupsToSets\ndef zap : Nat := "s"')
    assert rep["status"] == "error", rep
    print("ok: registry mutation in a failed cell rolled back with it")

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
