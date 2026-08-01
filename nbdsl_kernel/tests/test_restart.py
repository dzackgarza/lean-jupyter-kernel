"""Recovery laws for the production WorkerClient, against a real worker.

Both cases below were shipped defects, reproduced here first as red tests:

  A. a worker dying mid-replay consumed the replay ledger, so the NEXT restart
     replayed the stump and reported success over a half-empty environment —
     committed definitions vanished with no error;
  B. a session restored from cache and killed AGAIN aborted the worker with
     "Stack overflow detected", because saving a restored state wrote an olean
     that imported itself.

The worker package is its own Lean project and its prelude is `Init`, so these
run mathlib-free in seconds and hold no multi-GB session. Every test shuts its
worker down in a finally.

Run: .venv/bin/pytest nbdsl_kernel/tests/test_restart.py
"""

import concurrent.futures
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psutil
import pytest
from jupyter_client.kernelspec import KernelSpecManager
from jupyter_client.manager import KernelManager
from jupyter_client.provisioning import LocalProvisioner
from nbdsl_kernel.worker import LIVENESS_SLICE, WorkerClient, WorkerDied
from test_e2e import run_cell, texts

REPO = Path(__file__).resolve().parents[2]
# The middle cell fails when — and only when — the respawned worker inherits
# FAIL_VAR: it commits normally the first time and breaks partway through
# replay. Deterministic, no timing race, nothing mocked. A worker that *dies*
# mid-replay truncated the ledger through this same handler (the raise below
# and a WorkerDied from the transport share one try block), and a real death
# is not usable here: an exiting worker leaves `lake env` holding the reply
# pipe, so the client waits out its full reply timeout instead of failing.
FAIL_VAR = "NBDSL_TEST_FAIL_ON_REPLAY"
DIVERGE = ('#eval (do if (← IO.getEnv "' + FAIL_VAR
           + '") == some "1" then throw (IO.userError "replay divergence") '
           ': IO Unit)')
CELLS = ["def alpha : Nat := 11", DIVERGE, "def gamma : Nat := alpha + 2"]


@pytest.fixture
def client() -> Iterator[WorkerClient]:
    w = WorkerClient(REPO / "worker", prelude="Init")
    try:
        w.start()
        yield w
    finally:
        w.kill()          # never leave a worker behind, even on failure
        w.shutdown()


def commit_cells(w: WorkerClient) -> None:
    for i, code in enumerate(CELLS):
        assert w.execute(code, cell_id=f"c{i}").status == "ok", code
        if w.cache_dir:
            w.save_session()


def test_healthy_worker_stays_live_across_liveness_slices(
        client: WorkerClient) -> None:
    """A genuinely quiet live worker must survive repeated status probes."""
    wait_ms = int((LIVENESS_SLICE + 1) * 1000)
    rep = client.execute(
        f"#eval (do IO.sleep {wait_ms}; IO.println (6 * 7) : IO Unit)",
        cell_id="quiet-live-worker")
    assert rep.status == "ok", rep
    assert any("42" in diagnostic.message for diagnostic in rep.diagnostics), rep


def test_replay_failure_keeps_the_committed_ledger(
        client: WorkerClient) -> None:
    """A worker that dies mid-replay must not consume the canonical record."""
    w = client
    commit_cells(w)
    assert len(w.ledger) == len(CELLS)

    w.kill()
    os.environ[FAIL_VAR] = "1"        # the respawned worker inherits this
    try:
        with pytest.raises(WorkerDied):
            w.restart_and_replay()
    finally:
        del os.environ[FAIL_VAR]

    # The defect: the ledger was left truncated to whatever replay reached.
    assert len(w.ledger) == len(CELLS), w.ledger
    # And the state it describes really is reconstructible.
    assert w.restart_and_replay() == len(CELLS)
    rep = w.execute("#eval gamma", cell_id="check")
    assert rep.status == "ok", rep
    assert any("13" in d.message for d in rep.diagnostics), rep


def test_the_diverging_cell_really_diverges() -> None:
    """Guard the test above: a worker that inherits the flag must fail this
    cell. Without it the replay would quietly succeed and prove nothing — and
    the other tests' `commit_cells` already proves the flagless case commits.
    (The flag is read at worker startup, so this needs its own process.)"""
    os.environ[FAIL_VAR] = "1"
    try:
        w = WorkerClient(REPO / "worker", prelude="Init")
        w.start()
        try:
            assert w.execute(DIVERGE, cell_id="s").status == "error"
        finally:
            w.kill()
            w.shutdown()
    finally:
        del os.environ[FAIL_VAR]


def _child_pids(parent: int) -> dict[int, list[int]]:
    tree: dict[int, list[int]] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            status = (entry / "status").read_text()
        except OSError:
            continue
        for line in status.splitlines():
            if line.startswith("PPid:"):
                tree.setdefault(int(line.split()[1]), []).append(int(entry.name))
                break
    return tree


def _worker_and_wrapper(kernel_pid: int) -> tuple[int, int]:
    """(worker pid, its direct parent pid) under the kernel process."""
    tree = _child_pids(kernel_pid)
    stack = [kernel_pid]
    while stack:
        parent = stack.pop()
        for pid in tree.get(parent, []):
            stack.append(pid)
            try:
                if Path(os.readlink(f"/proc/{pid}/exe")).name == "nbdsl_worker":
                    return pid, parent
            except OSError:
                continue
    raise AssertionError(f"no live nbdsl_worker under {kernel_pid}")


def _await_execute(
        kc: Any, msg_id: str, timeout: float = 120) -> tuple[dict[str, Any],
                                                             list[Any]]:
    outputs = []
    while True:
        msg = kc.get_iopub_msg(timeout=timeout)
        if msg["parent_header"].get("msg_id") != msg_id:
            continue
        if (msg["msg_type"] == "status"
                and msg["content"]["execution_state"] == "idle"):
            break
        outputs.append(msg)
    while True:
        reply = kc.get_shell_msg(timeout=timeout)
        if reply["parent_header"].get("msg_id") == msg_id:
            return reply["content"], outputs


def test_sandbox_ready_pid_is_the_host_observable_worker() -> None:
    """Host-side liveness owns a host PID even under Bubblewrap's PID
    namespace; a namespace-local ready PID cannot satisfy that contract.
    """
    prior = os.environ.get("NBDSL_SANDBOX")
    os.environ["NBDSL_SANDBOX"] = "1"
    w = WorkerClient(REPO / "worker", prelude="Init")
    try:
        ready = w.start()
        assert w.proc is not None
        host_worker, _ = _worker_and_wrapper(w.proc.pid)
        assert ready.pid == host_worker, {
            "ready_pid": ready.pid,
            "host_worker_pid": host_worker,
        }
    finally:
        w.shutdown()
        if prior is None:
            del os.environ["NBDSL_SANDBOX"]
        else:
            os.environ["NBDSL_SANDBOX"] = prior


def test_a_worker_death_under_a_live_wrapper_recovers_transparently(
        tmp_path: Path) -> None:
    """The restart branch used to be gated ONLY on poll() of the `lake env`
    wrapper. A worker that dies while its wrapper lives (a crash, an OOM kill,
    the wrapper merely not yet reaped) evaded it: the kernel wrote to the dead
    worker and answered a spurious WorkerDied instead of restarting. SIGSTOP
    on the wrapper holds that window open deterministically."""
    data = tmp_path / "jupyter"
    env = {k: v for k, v in os.environ.items()
           if k not in {"PYTHONPATH", "VIRTUAL_ENV", "JUPYTER_DATA_DIR",
                        "NBDSL_INIT"}}
    subprocess.run(
        [sys.executable, "-m", "nbdsl_kernel.install",
         "--project", str(REPO / "worker"), "--name", "restart-race",
         "--prelude-module", "Init"],
        env={**env, "JUPYTER_DATA_DIR": str(data)}, check=True,
        capture_output=True)
    ksm = KernelSpecManager(kernel_dirs=[str(data / "kernels")])
    km = KernelManager(kernel_name="restart-race", kernel_spec_manager=ksm)
    km.start_kernel(env=env)
    kc: Any = km.client()
    kc.start_channels()
    wrapper = -1
    try:
        kc.wait_for_ready(timeout=120)
        reply, _ = run_cell(kc, "def x : Nat := 41", timeout=120)
        assert reply["status"] == "ok", reply
        prov = km.provisioner
        assert isinstance(prov, LocalProvisioner) and prov.process is not None
        worker, wrapper = _worker_and_wrapper(prov.process.pid)
        os.kill(wrapper, signal.SIGSTOP)   # the wrapper can neither exit nor reap
        os.kill(worker, signal.SIGKILL)    # the worker becomes its zombie child
        zombie_deadline = time.monotonic() + LIVENESS_SLICE
        while psutil.Process(worker).status() != psutil.STATUS_ZOMBIE:
            assert time.monotonic() < zombie_deadline
            time.sleep(0.01)
        reply, outputs = run_cell(kc, "#eval x + 1", timeout=120)
        assert reply["status"] == "ok", reply
        text = texts(outputs)
        assert "42" in text, text
        assert "Lean worker died; restarting" in text, text
    finally:
        if wrapper > 0:
            try:
                os.kill(wrapper, signal.SIGCONT)
            except ProcessLookupError:
                pass
        kc.stop_channels()
        km.shutdown_kernel(now=True)


def test_worker_death_after_external_effect_does_not_rerun_the_cell(
        tmp_path: Path) -> None:
    """Once an external effect is visible, a missing reply is uncertain and
    the kernel must not manufacture success by executing the cell again.
    """
    data = tmp_path / "jupyter"
    effect = tmp_path / "effect.log"
    env = {k: v for k, v in os.environ.items()
           if k not in {"PYTHONPATH", "VIRTUAL_ENV", "JUPYTER_DATA_DIR",
                        "NBDSL_INIT"}}
    subprocess.run(
        [
            sys.executable,
            "-m",
            "nbdsl_kernel.install",
            "--project",
            str(REPO / "worker"),
            "--name",
            "effect-once",
            "--prelude-module",
            "Init",
        ],
        env={**env, "JUPYTER_DATA_DIR": str(data)},
        check=True,
        capture_output=True,
    )
    ksm = KernelSpecManager(kernel_dirs=[str(data / "kernels")])
    km = KernelManager(kernel_name="effect-once", kernel_spec_manager=ksm)
    km.start_kernel(env=env)
    kc: Any = km.client()
    kc.start_channels()
    wrapper = -1
    try:
        kc.wait_for_ready(timeout=120)
        path = json.dumps(str(effect))
        code = (
            "#eval (do\n"
            f"  let h ← IO.FS.Handle.mk {path} .append\n"
            '  h.putStrLn "effect"\n'
            "  h.flush\n"
            f"  let contents ← IO.FS.readFile {path}\n"
            '  if contents == "effect\\n" then IO.sleep 30000 else pure ()\n'
            "  : IO Unit)"
        )
        msg_id = kc.execute(code)
        effect_deadline = time.monotonic() + 120
        while not effect.exists() or effect.read_text() != "effect\n":
            assert time.monotonic() < effect_deadline
            time.sleep(0.01)

        provisioner = km.provisioner
        assert isinstance(provisioner, LocalProvisioner)
        assert provisioner.process is not None
        worker, wrapper = _worker_and_wrapper(provisioner.process.pid)
        os.kill(wrapper, signal.SIGSTOP)
        os.kill(worker, signal.SIGKILL)

        reply, outputs = _await_execute(kc, msg_id)
        effects = effect.read_text().splitlines()
        assert effects == ["effect"], {
            "effects": effects,
            "reply": reply,
            "outputs": outputs,
        }
        assert reply["status"] == "error", reply
    finally:
        if wrapper > 0:
            try:
                os.kill(wrapper, signal.SIGCONT)
            except ProcessLookupError:
                pass
        kc.stop_channels()
        km.shutdown_kernel(now=True)


def test_partial_reply_then_worker_death_is_bounded_and_recoverable(
        client: WorkerClient) -> None:
    """A real oversized worker reply is killed only after the production
    decoder has consumed a strict prefix; the stopped wrapper keeps its pipe
    ends open, so only the worker liveness probe can end the wait.
    """
    reply_bytes = 32 * 1024 * 1024
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(
            client.execute,
            f"#eval String.ofList (List.replicate {reply_bytes} 'x')",
            "partial-frame")
        partial_deadline = time.monotonic() + 120
        while True:
            assert client.replies is not None
            buffered = len(client.replies.buf)
            if 0 < buffered < reply_bytes:
                break
            assert time.monotonic() < partial_deadline
            time.sleep(0.001)

        assert client.proc is not None
        assert client.worker_pid is not None
        os.kill(client.proc.pid, signal.SIGSTOP)
        os.kill(client.worker_pid, signal.SIGKILL)
        with pytest.raises(WorkerDied):
            future.result(timeout=LIVENESS_SLICE + 2)

        client.kill()
        client.start()
        rep = client.execute("#eval 6 * 7", cell_id="after-partial-death")
        assert rep.status == "ok", rep
        assert any("42" in diagnostic.message
                   for diagnostic in rep.diagnostics), rep
    finally:
        client.kill()
        executor.shutdown(wait=True)


def test_second_recovery_of_a_restored_session(client: WorkerClient) -> None:
    """Restore, run, kill, restore again: the second recovery used to abort
    the worker with a stack overflow."""
    w = client
    w.cache_dir = tempfile.mkdtemp(prefix="nbdsl-test-cache-")
    commit_cells(w)

    w.kill()
    assert w.restart_and_replay() == -1, "first recovery should use the cache"
    assert w.execute("def delta : Nat := gamma + 1", cell_id="d").status == "ok"
    w.save_session()

    w.kill()
    assert w.restart_and_replay() == -1, "second recovery should use the cache"
    rep = w.execute("#eval delta", cell_id="check")
    assert rep.status == "ok", rep
    assert any("14" in d.message for d in rep.diagnostics), rep


def test_restart_signals_a_shared_wrapper_worker_group_once(
        client: WorkerClient) -> None:
    assert client.proc is not None
    assert client.worker_pid is not None
    old_group = os.getpgid(client.proc.pid)
    assert os.getpgid(client.worker_pid) == old_group

    signals: list[tuple[str, int]] = []

    def record_signal(event: str, args: tuple[object, ...]) -> None:
        if event in {"os.kill", "os.killpg"} and args[1] == signal.SIGKILL:
            target = args[0]
            assert isinstance(target, int)
            signals.append((event, target))

    sys.addaudithook(record_signal)

    assert client.restart_and_replay() == 0
    assert signals == [("os.killpg", old_group)]

    rep = client.execute("#eval 6 * 7", cell_id="after-single-group-kill")
    assert rep.status == "ok", rep
    assert any("42" in diagnostic.message
               for diagnostic in rep.diagnostics), rep
