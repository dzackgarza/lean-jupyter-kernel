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

import os
import tempfile
from pathlib import Path
from typing import Iterator

import pytest

from nbdsl_kernel.worker import WorkerClient, WorkerDied

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
