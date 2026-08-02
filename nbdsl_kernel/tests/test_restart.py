"""Recovery laws for the production WorkerClient, against a real worker.

Both cases below were shipped defects, reproduced here first as red tests:

  A. a worker dying mid-replay consumed the replay ledger, so the NEXT restart
     replayed the stump and reported success over a half-empty environment —
     committed definitions vanished with no error;
  B. a session restored from cache and killed AGAIN aborted the worker with
     "Stack overflow detected", because saving a restored state wrote an olean
     that imported itself.

The worker package is its own Lean project and its prelude is `Init`, so these
run mathlib-free in seconds. Every test shuts its worker down in a finally.

Run: .venv/bin/pytest nbdsl_kernel/tests/test_restart.py
"""

from __future__ import annotations

import json
import os
import signal
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import psutil
import pytest
from jupyter_client.provisioning import LocalProvisioner
from nbdsl_kernel.worker import LIVENESS_SLICE, WorkerClient, WorkerDied
from test_e2e import run_cell, texts

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
        if w.cache_dir:
            w.save_session()


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


def test_replay_failure_keeps_the_committed_ledger(
        client: WorkerClient) -> None:
    """A worker that dies mid-replay must not consume the canonical record."""
    w = client
    commit_cells(w)
    assert len(w.ledger) == len(CELLS)

    w.kill()
    os.environ[FAIL_VAR] = "1"
    try:
        with pytest.raises(WorkerDied):
            w.restart_and_replay()
    finally:
        del os.environ[FAIL_VAR]

    assert len(w.ledger) == len(CELLS), w.ledger
    assert w.restart_and_replay() == len(CELLS)
    rep = w.execute("#eval gamma", cell_id="check")
    assert rep.status == "ok", rep
    assert any("13" in d.message for d in rep.diagnostics), rep


def test_second_recovery_of_a_restored_session(client: WorkerClient) -> None:
    """Restore, run, kill, restore again: the second recovery used to abort."""
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


def test_a_worker_death_under_a_live_wrapper_recovers_transparently(
        tmp_path: Path) -> None:
    """SIGSTOP on the wrapper keeps a dead-worker window open deterministically."""
    km, kc = start_init_kernel(tmp_path, "restart-race")
    wrapper = -1
    try:
        reply, _ = run_cell(kc, "def x : Nat := 41", timeout=120)
        assert reply["status"] == "ok", reply
        prov = km.provisioner
        assert isinstance(prov, LocalProvisioner) and prov.process is not None
        worker, wrapper = find_worker_under(prov.process.pid)
        os.kill(wrapper, signal.SIGSTOP)
        os.kill(worker, signal.SIGKILL)
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
    """Once an external effect is visible, a missing reply must not re-execute."""
    km, kc = start_init_kernel(tmp_path, "effect-once")
    effect = tmp_path / "effect.log"
    wrapper = -1
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
        worker, wrapper = find_worker_under(provisioner.process.pid)
        os.kill(wrapper, signal.SIGSTOP)
        os.kill(worker, signal.SIGKILL)

        reply, outputs = await_execute(kc, msg_id)
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
