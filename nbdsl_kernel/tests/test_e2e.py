"""End-to-end invariants through the real Jupyter kernel protocol.

Drives the installed `nbdsl` kernelspec with jupyter_client, exercising the
whole stack: ZMQ → NbDslKernel → framed fds → nbdsl_worker → Lean.

Run: .venv/bin/pytest nbdsl_kernel/tests/test_e2e.py   (after install.py)
"""

import queue

import pytest
from jupyter_client.manager import start_new_kernel

STARTUP = 600  # first execute waits for the worker's prelude import


@pytest.fixture(scope="module")
def kernel():
    km, kc = start_new_kernel(kernel_name="nbdsl", startup_timeout=60)
    yield km, kc
    kc.stop_channels()
    km.shutdown_kernel(now=False)


def run_cell(kc, code, timeout=STARTUP):
    """Execute code, return (reply, iopub messages up to idle)."""
    msg_id = kc.execute(code)
    outputs = []
    while True:
        msg = kc.get_iopub_msg(timeout=timeout)
        if msg["parent_header"].get("msg_id") != msg_id:
            continue
        if (msg["msg_type"] == "status"
                and msg["content"]["execution_state"] == "idle"):
            break
        outputs.append(msg)
    reply = kc.get_shell_msg(timeout=timeout)
    assert reply["parent_header"]["msg_id"] == msg_id
    return reply["content"], outputs


def texts(outputs, name=None):
    return "".join(
        m["content"]["text"] for m in outputs
        if m["msg_type"] == "stream" and (name is None or m["content"]["name"] == name))


def test_eval_and_state(kernel):
    _, kc = kernel
    reply, _ = run_cell(kc, "def x : Nat := 41")
    assert reply["status"] == "ok"
    reply, outputs = run_cell(kc, "#eval x + 1")
    assert reply["status"] == "ok"
    assert "42" in texts(outputs)


def test_failure_isolation(kernel):
    _, kc = kernel
    reply, outputs = run_cell(kc, 'def broken : Nat := "s"')
    assert reply["status"] == "error"
    assert any(m["msg_type"] == "error" for m in outputs)
    reply, outputs = run_cell(kc, "#eval x + 1")  # prior state intact
    assert reply["status"] == "ok"
    assert "42" in texts(outputs)


def test_dsl_structured_output(kernel):
    _, kc = kernel
    for cell in ("open NbDsl NbDsl.Std",
                 "prefer groupsToSets",
                 "let G := GrpCat.of PUnit ∈ Groups"):
        reply, _ = run_cell(kc, cell)
        assert reply["status"] == "ok", cell
    reply, outputs = run_cell(kc, "#via G ∈ Sets")
    assert reply["status"] == "ok"
    bundles = [m["content"]["data"] for m in outputs
               if m["msg_type"] in ("execute_result", "display_data")]
    assert any("application/vnd.nbdsl.path+json" in b for b in bundles)


def test_complete_and_inspect(kernel):
    _, kc = kernel
    # Self-contained: bare-name completion depends on this committed open.
    reply, _ = run_cell(kc, "open NbDsl NbDsl.Std")
    assert reply["status"] == "ok"
    msg_id = kc.complete("prefer groupsToS", 16)
    reply = kc.get_shell_msg(timeout=60)
    assert reply["parent_header"]["msg_id"] == msg_id
    assert "groupsToSets" in reply["content"]["matches"], reply["content"]
    msg_id = kc.inspect("groupsToSets", 0)
    reply = kc.get_shell_msg(timeout=60)
    assert reply["parent_header"]["msg_id"] == msg_id
    content = reply["content"]
    assert content["found"], content
    text = content["data"]["text/plain"]
    assert "Functor" in text or "⥤" in text, text


def _send_comm(kc, msg_type, content):
    msg = kc.session.msg(msg_type, content)
    kc.shell_channel.send(msg)


def _send_document(kc, comm_id, cells):
    _send_comm(kc, "comm_msg", {
        "comm_id": comm_id,
        "data": {"type": "document",
                 "cells": [{"id": i, "source": s} for i, s in cells]}})


def _exec_cell(kc, code, cell_id, timeout=STARTUP):
    """execute_request with JupyterLab's metadata.cellId, like the frontend."""
    msg = kc.session.msg("execute_request", {
        "code": code, "silent": False, "store_history": True,
        "user_expressions": {}, "allow_stdin": False})
    msg["metadata"] = {"cellId": cell_id}
    kc.shell_channel.send(msg)
    msg_id = msg["header"]["msg_id"]
    outputs = []
    while True:
        m = kc.get_iopub_msg(timeout=timeout)
        if m["parent_header"].get("msg_id") != msg_id:
            continue
        if (m["msg_type"] == "status"
                and m["content"]["execution_state"] == "idle"):
            break
        outputs.append(m)
    while True:
        reply = kc.get_shell_msg(timeout=timeout)
        if reply["parent_header"]["msg_id"] == msg_id:
            return reply["content"], outputs


def test_interrupt_restart_replay(kernel):
    km, kc = kernel
    msg_id = kc.execute("def spin : IO Unit := do while true do pure ()\n#eval spin")
    # Give elaboration a moment to be genuinely stuck, then interrupt.
    try:
        kc.get_shell_msg(timeout=5)
        pytest.fail("infinite cell returned unexpectedly")
    except queue.Empty:
        pass
    km.interrupt_kernel()
    reply = kc.get_shell_msg(timeout=STARTUP)  # restart + replay happens here
    assert reply["parent_header"]["msg_id"] == msg_id
    # Drain iopub to idle before the next cell.
    while True:
        msg = kc.get_iopub_msg(timeout=30)
        if (msg["parent_header"].get("msg_id") == msg_id
                and msg["msg_type"] == "status"
                and msg["content"]["execution_state"] == "idle"):
            break
    # Replay must have reconstructed every committed cell.
    reply, outputs = run_cell(kc, "#eval x + 1")
    assert reply["status"] == "ok"
    assert "42" in texts(outputs)


def test_document_order_semantics(kernel):
    _, kc = kernel
    comm_id = "doc-comm-1"
    _send_comm(kc, "comm_open", {"comm_id": comm_id,
                                 "target_name": "nbdsl_document", "data": {}})
    # Two cells; running the SECOND must auto-run the first (prefix invariant).
    _send_document(kc, comm_id, [("cellA", "def base : Nat := 1"),
                                 ("cellB", "#eval base + 1")])
    reply, outputs = _exec_cell(kc, "#eval base + 1", "cellB")
    assert reply["status"] == "ok", reply
    text = texts(outputs)
    assert "re-running upstream cell 1" in text, text
    assert "2" in text, text

    # Editing the upstream cell invalidates downstream: same run now sees 5.
    _send_document(kc, comm_id, [("cellA", "def base : Nat := 5"),
                                 ("cellB", "#eval base + 1")])
    reply, outputs = _exec_cell(kc, "#eval base + 1", "cellB")
    assert reply["status"] == "ok", reply
    assert "6" in texts(outputs), texts(outputs)

    # Unchanged prefix is NOT re-run.
    reply, outputs = _exec_cell(kc, "#eval base + 1", "cellB")
    assert reply["status"] == "ok", reply
    assert "re-running" not in texts(outputs), texts(outputs)

    # A broken upstream cell surfaces as this cell's failure, atomically.
    _send_document(kc, comm_id, [("cellA", 'def base : Nat := "no"'),
                                 ("cellB", "#eval base + 1")])
    reply, outputs = _exec_cell(kc, "#eval base + 1", "cellB")
    assert reply["status"] == "error", reply
    assert "upstream cell 1" in reply["evalue"], reply

