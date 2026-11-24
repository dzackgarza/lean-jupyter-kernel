"""Session-loss laws for the production WorkerClient, against the real worker.

Keep the former replay-divergence and repeated-cache-restoration source controls.
Protocol 2 explicitly forbids either recovery mechanism: the tests now require
a new nonce, no recovered definitions, and no automatic execution of saved source.
The Init prelude builds without Mathlib.
"""

from __future__ import annotations

import json
import os
import queue
import signal
import time
from collections.abc import Iterator
from pathlib import Path

import psutil
import pytest
from jupyter_client.provisioning import LocalProvisioner
from nbdsl_kernel.worker import WorkerClient, WorkerDied
from nbdsl_kernel.worker.errors import WireProtocolError
from test_e2e import run_cell

from jupyter_helpers import (
    REPO,
    await_execute,
    find_worker_under,
    start_init_kernel,
)

# The middle cell fails when — and only when — the respawned worker inherits
# FAIL_VAR: it commits normally the first time and breaks partway through
# replay. Deterministic, no timing race, nothing mocked.
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
        w.kill()
        w.shutdown()


def commit_cells(w: WorkerClient) -> None:
    for i, code in enumerate(CELLS):
        assert w.execute(code, cell_id=f"c{i}").status == "ok", code


def test_the_diverging_cell_really_diverges() -> None:
    """Guard the ledger test: with FAIL_VAR set, the diverge cell must error."""
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


def test_replay_is_rejected_and_no_committed_source_is_recovered(
        client: WorkerClient, monkeypatch: pytest.MonkeyPatch) -> None:
    w = client
    commit_cells(w)
    old_nonce, old_snapshot = w.worker_nonce, w.snapshot
    rep = w.execute("#eval gamma", cell_id="check")
    assert rep.status == "ok" and any("13" in d.message for d in rep.diagnostics), rep
    w.kill()
    monkeypatch.setenv(FAIL_VAR, "1")
    with pytest.raises(WireProtocolError, match="cas_no_replay"):
        w.restart_and_replay()
    assert not w.running()
    w.restart_fresh()
    assert w.worker_nonce != old_nonce and w.snapshot == 0
    absent = w.execute_at("#eval gamma", "old-parent", old_snapshot)
    assert absent.status == "error" and absent.reason == "snapshot_unavailable", absent
    assert absent.commit is None and not absent.outputs
    assert w.execute("#eval gamma").status == "error"
    # The exact original source still fails when explicitly submitted.
    assert w.execute(DIVERGE).status == "error"


def test_repeated_fresh_session_never_restores_a_cache(client: WorkerClient) -> None:
    w = client
    commit_cells(w)
    assert w.execute("def delta : Nat := gamma + 1", cell_id="d").status == "ok"
    rep = w.execute("#eval delta", cell_id="check")
    assert rep.status == "ok" and any("14" in d.message for d in rep.diagnostics), rep
    nonces = {w.worker_nonce}
    for _ in range(2):
        w.restart_fresh()
        assert w.worker_nonce not in nonces and w.snapshot == 0
        nonces.add(w.worker_nonce)
        assert w.execute("#eval delta").status == "error"
        assert not hasattr(w, "cache_dir") and not hasattr(w, "ledger")
        # Deliberate resubmission is allowed; it is not recovery.
        commit_cells(w)
        assert w.execute("def delta : Nat := gamma + 1", cell_id="d").status == "ok"


def test_worker_death_is_reported_without_restarting(tmp_path: Path) -> None:
    """A dead worker stays absent, even on a subsequent explicit execute."""
    km, kc = start_init_kernel(tmp_path, "restart-race")
    try:
        reply, _ = run_cell(kc, "def x : Nat := 41", timeout=120)
        assert reply["status"] == "ok", reply
        prov = km.provisioner
        assert isinstance(prov, LocalProvisioner) and prov.process is not None
        worker, _ = find_worker_under(prov.process.pid)
        os.kill(worker, signal.SIGKILL)
        deadline = time.monotonic() + 5.0
        while True:
            try:
                if psutil.Process(worker).status() == psutil.STATUS_ZOMBIE:
                    break
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                break
            assert time.monotonic() < deadline, f"worker {worker} still live"
            time.sleep(0.01)
        reply, outputs = run_cell(kc, "#eval x + 1", timeout=120)
        assert reply["status"] == "error", reply
        assert "worker_absent" in reply["evalue"], reply
        assert not any(m["msg_type"] == "stream" and "42" in m["content"].get("text", "")
                       for m in outputs), outputs
        assert not psutil.pid_exists(worker) or psutil.Process(worker).status() == psutil.STATUS_ZOMBIE
    finally:
        kc.stop_channels()
        km.shutdown_kernel(now=True)


def test_worker_death_after_external_effect_does_not_rerun_the_cell(
        tmp_path: Path) -> None:
    """Once an external effect is visible, a missing reply must not re-execute."""
    km, kc = start_init_kernel(tmp_path, "effect-once")
    effect = tmp_path / "effect.log"
    try:
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
        worker, _ = find_worker_under(provisioner.process.pid)
        os.kill(worker, signal.SIGKILL)

        reply, outputs = await_execute(kc, msg_id)
        effects = effect.read_text().splitlines()
        assert effects == ["effect"], {
            "effects": effects,
            "reply": reply,
            "outputs": outputs,
        }
        assert reply["status"] == "error", reply
        assert "connection_lost_after_send" in reply["evalue"], reply
        next_reply, _ = run_cell(kc, code, timeout=120)
        assert next_reply["status"] == "error" and "worker_absent" in next_reply["evalue"], next_reply
        assert effect.read_text().splitlines() == ["effect"]
    finally:
        kc.stop_channels()
        km.shutdown_kernel(now=True)


def test_noncooperative_interrupt_does_not_force_or_replay(tmp_path: Path) -> None:
    """The original interpreted spin cannot license transparent replacement."""
    km, kc = start_init_kernel(tmp_path, "noncooperative-cancel")
    marker = tmp_path / "entered"
    owned: psutil.Process | None = None
    try:
        reply, _ = run_cell(kc, "def x : Nat := 41")
        assert reply["status"] == "ok", reply
        provisioner = km.provisioner
        assert isinstance(provisioner, LocalProvisioner) and provisioner.process is not None
        worker, _ = find_worker_under(provisioner.process.pid)
        owned = psutil.Process(worker)
        code = (
            "def spin : IO Unit := do while true do pure ()\n"
            "#eval (do\n"
            f"  IO.FS.writeFile {json.dumps(str(marker))} \"entered\"\n"
            "  spin : IO Unit)"
        )
        request_id = kc.execute(code)
        deadline = time.monotonic() + 120
        while not marker.exists():
            assert time.monotonic() < deadline, "the actual interpreted loop never started"
            try:
                early = kc.get_shell_msg(timeout=0.05)
            except queue.Empty:
                continue
            if early["parent_header"].get("msg_id") == request_id:
                pytest.fail(f"the interpreted loop returned before its marker: {early['content']}")
        km.interrupt_kernel()
        reply, _ = await_execute(kc, request_id)
        assert reply["status"] == "error", reply
        # The worker acknowledges the cancellation but this interpreted IO
        # action never returns. The missing original reply is draining, not
        # an unacknowledged cancellation, and cannot license a replay.
        assert "unavailable/draining" in reply["evalue"], reply
        assert psutil.pid_exists(worker), "cooperative interrupt forced the worker"
        current, _ = find_worker_under(provisioner.process.pid)
        assert current == worker, "the adapter started a replacement session"
    finally:
        kc.stop_channels()
        # The non-returning worker has its own process group. Explicit test
        # disposal must close it even when Jupyter kills its kernel parent.
        if owned is not None and owned.is_running():
            try:
                owned.kill()
            except psutil.NoSuchProcess:
                pass
        km.shutdown_kernel(now=True)
