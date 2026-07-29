"""End-to-end invariants through the real Jupyter kernel protocol.

Drives the installed `nbdsl` kernelspec with jupyter_client, exercising the
whole stack: ZMQ → NbDslKernel → framed fds → nbdsl_worker → Lean.

Run: .venv/bin/pytest nbdsl_kernel/tests/test_e2e.py   (after install.py)
"""

import queue
from typing import Any, Iterator

import pytest
from jupyter_client.manager import start_new_kernel

# jupyter_client's manager/client classes are traitlets-heavy; Any keeps
# the tests honest without stubbing a dependency we don't own.
Kernel = tuple[Any, Any]  # (KernelManager, BlockingKernelClient)

STARTUP = 600  # first execute waits for the worker's prelude import


@pytest.fixture(scope="module")
def kernel() -> Iterator[Kernel]:
    km, kc = start_new_kernel(kernel_name="nbdsl", startup_timeout=60)
    yield km, kc
    kc.stop_channels()
    km.shutdown_kernel(now=False)


def run_cell(kc: Any, code: str,
             timeout: float = STARTUP) -> tuple[dict[str, Any], list[Any]]:
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


def texts(outputs: list[Any], name: str | None = None) -> str:
    return "".join(
        m["content"]["text"] for m in outputs
        if m["msg_type"] == "stream" and (name is None or m["content"]["name"] == name))


def test_eval_and_state(kernel: Kernel) -> None:
    _, kc = kernel
    reply, _ = run_cell(kc, "def x : Nat := 41")
    assert reply["status"] == "ok"
    reply, outputs = run_cell(kc, "#eval x + 1")
    assert reply["status"] == "ok"
    assert "42" in texts(outputs)


def test_failure_isolation(kernel: Kernel) -> None:
    _, kc = kernel
    reply, outputs = run_cell(kc, 'def broken : Nat := "s"')
    assert reply["status"] == "error"
    assert any(m["msg_type"] == "error" for m in outputs)
    reply, outputs = run_cell(kc, "#eval x + 1")  # prior state intact
    assert reply["status"] == "ok"
    assert "42" in texts(outputs)


def test_dsl_structured_output(kernel: Kernel) -> None:
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


def test_complete_and_inspect(kernel: Kernel) -> None:
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


def _send_comm(kc: Any, msg_type: str, content: dict[str, Any]) -> None:
    msg = kc.session.msg(msg_type, content)
    kc.shell_channel.send(msg)


def _send_document(kc: Any, comm_id: str,
                   cells: list[tuple[str, str]]) -> None:
    _send_comm(kc, "comm_msg", {
        "comm_id": comm_id,
        "data": {"type": "document",
                 "cells": [{"id": i, "source": s} for i, s in cells]}})


def _exec_cell(kc: Any, code: str, cell_id: str,
               timeout: float = STARTUP) -> tuple[dict[str, Any], list[Any]]:
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
            content: dict[str, Any] = reply["content"]
            return content, outputs


def test_interrupt_restart_replay(kernel: Kernel) -> None:
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
    # Recovery must reconstruct committed state — via the session cache
    # (olean round-trip), not replay.
    reply, outputs = run_cell(kc, "#eval x + 1")
    assert reply["status"] == "ok"
    text = texts(outputs)
    assert "42" in text
    assert "Restored session from cache" in text, text
    # Registry (env-extension) state survived the olean round-trip.
    reply, outputs = run_cell(kc, "#via G ∈ Sets")
    assert reply["status"] == "ok"
    assert any("application/vnd.nbdsl.path+json" in m["content"].get("data", {})
               for m in outputs
               if m["msg_type"] in ("execute_result", "display_data")), \
        [m["msg_type"] for m in outputs]


def test_uncacheable_state_falls_back_to_replay(kernel: Kernel) -> None:
    km, kc = kernel
    # An open `section` makes the state uncacheable (the worker refuses to
    # save and the cache key is dropped), so the next worker death must
    # recover by source replay — the validated-cache miss path.
    reply, _ = run_cell(kc, "section")
    assert reply["status"] == "ok"
    msg_id = kc.execute(
        "def spin2 : IO Unit := do while true do pure ()\n#eval spin2")
    try:
        kc.get_shell_msg(timeout=5)
        pytest.fail("infinite cell returned unexpectedly")
    except queue.Empty:
        pass
    km.interrupt_kernel()
    reply = kc.get_shell_msg(timeout=STARTUP)
    assert reply["parent_header"]["msg_id"] == msg_id
    while True:
        msg = kc.get_iopub_msg(timeout=30)
        if (msg["parent_header"].get("msg_id") == msg_id
                and msg["msg_type"] == "status"
                and msg["content"]["execution_state"] == "idle"):
            break
    reply, outputs = run_cell(kc, "#eval x + 1")
    assert reply["status"] == "ok"
    text = texts(outputs)
    assert "42" in text
    assert "Replayed" in text and "Restored session" not in text, text
    reply, _ = run_cell(kc, "end")  # close the section again
    assert reply["status"] == "ok"


def _await_status(kc: Any, timeout: float = 15) -> dict[str, Any]:
    while True:
        msg = kc.get_iopub_msg(timeout=timeout)
        if (msg["msg_type"] == "comm_msg"
                and msg["content"].get("data", {}).get("type") == "status"):
            data: dict[str, Any] = msg["content"]["data"]
            return data


def _drain_iopub(kc: Any) -> None:
    while True:
        try:
            kc.get_iopub_msg(timeout=0.5)
        except queue.Empty:
            return


def test_init_cell() -> None:
    import os
    km, kc = start_new_kernel(
        kernel_name="nbdsl", startup_timeout=60,
        env={**os.environ, "NBDSL_INIT": "def initVal : Nat := 99"})
    try:
        reply, outputs = run_cell(kc, "#eval initVal + 1")
        assert reply["status"] == "ok", reply
        assert "100" in texts(outputs)
    finally:
        kc.stop_channels()
        km.shutdown_kernel(now=False)


def test_init_cell_failure_is_loud() -> None:
    import os
    km, kc = start_new_kernel(
        kernel_name="nbdsl", startup_timeout=60,
        env={**os.environ, "NBDSL_INIT": 'def broken : Nat := "not a Nat"'})
    try:
        # A broken kernelspec must fail every execute, typed — never run
        # silently without the configured session defaults.
        reply, _ = run_cell(kc, "#eval 1 + 1")
        assert reply["status"] == "error", reply
        assert reply["ename"] == "InitCellError", reply
    finally:
        kc.stop_channels()
        km.shutdown_kernel(now=False)


def test_document_order_semantics(kernel: Kernel) -> None:
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

    # The kernel's staleness computation is contract: an upstream edit marks
    # the edited cell and everything after it stale, nothing else.
    _drain_iopub(kc)
    _send_document(kc, comm_id, [("cellA", "def base : Nat := 7"),
                                 ("cellB", "#eval base + 1")])
    status = _await_status(kc)
    assert status["stale"] == ["cellA", "cellB"], status
    assert status["fresh"] == [], status
    reply, outputs = _exec_cell(kc, "#eval base + 1", "cellB")
    assert reply["status"] == "ok"
    assert "8" in texts(outputs)
    _drain_iopub(kc)
    _send_document(kc, comm_id, [("cellA", "def base : Nat := 7"),
                                 ("cellB", "#eval base + 1")])
    status = _await_status(kc)
    assert status["fresh"] == ["cellA", "cellB"], status
    assert status["stale"] == [], status

    # A broken upstream cell surfaces as this cell's failure, atomically —
    # typed as UpstreamError, naming the offending cell.
    _send_document(kc, comm_id, [("cellA", 'def base : Nat := "no"'),
                                 ("cellB", "#eval base + 1")])
    reply, outputs = _exec_cell(kc, "#eval base + 1", "cellB")
    assert reply["status"] == "error", reply
    assert reply["ename"] == "UpstreamError", reply
    assert "upstream cell 1" in reply["evalue"], reply

