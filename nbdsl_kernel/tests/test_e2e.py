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
