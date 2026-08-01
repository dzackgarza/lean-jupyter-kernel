"""Inspection must discriminate, even under a plugin catch-all production.

A plugin may declare a low-priority bare-term command (`lean-cas-dsl` does).
That production matches ANY cell, so the InfoTree node covering the cursor is
the syntax declaration itself — and its hover is its own docstring, which the
worker used to return, identically, for every input. Inspection became
non-discriminating for any plugin with a catch-all.

Reproduced here in plain Lean — no plugin needed, and mathlib-free: the
worker package is its own Lean project, and the `Lean` prelude is all a
catch-all declaration requires.

Run: .venv/bin/pytest nbdsl_kernel/tests/test_inspect.py
"""

from pathlib import Path
from typing import Iterator

import pytest

from nbdsl_kernel.protocol import CompleteOk, InspectOk
from nbdsl_kernel.worker import WorkerClient

REPO = Path(__file__).resolve().parents[2]

DOC = "CATCHALL-DOCSTRING-PROBE"
CATCHALL = f"""/-- {DOC} -/
syntax (priority := low) term : command

elab_rules : command
  | `(command| $_t:term) => pure ()
"""

PLUGIN_QUERY = r"""
open Lean Elab Command
open Worker (emitOutput)
syntax (priority := low) ident : command
elab_rules : command
  | `(command| $id:ident) => do
      if id.getId == `pluginName then
        emitOutput { data := [("text/plain", .str "plugin-value")] }
      else
        throwError "unknown plugin name"
"""


@pytest.fixture
def client() -> Iterator[WorkerClient]:
    w = WorkerClient(REPO / "worker", prelude="Lean")
    try:
        w.start()
        assert w.execute(CATCHALL, cell_id="catchall").status == "ok"
        yield w
    finally:
        w.kill()
        w.shutdown()


def test_catchall_does_not_answer_for_unknown_names(
        client: WorkerClient) -> None:
    rep = client.inspect("garbagename", 0)
    assert isinstance(rep, InspectOk), rep
    assert rep.found is False, rep
    assert rep.hover is None, rep


def test_catchall_does_not_shadow_a_real_constant(
        client: WorkerClient) -> None:
    rep = client.inspect("Nat.succ", 0)
    assert isinstance(rep, InspectOk), rep
    assert rep.found, rep
    assert DOC not in (rep.hover or ""), rep
    assert rep.name == "Nat.succ", rep
    assert rep.type_ == "Nat → Nat", rep


def test_distinct_inputs_get_distinct_answers(client: WorkerClient) -> None:
    """The property the defect broke: two different queries must not return
    one identical payload."""
    a = client.inspect("Nat.succ", 0)
    b = client.inspect("Nat.zero", 0)
    assert isinstance(a, InspectOk) and isinstance(b, InspectOk)
    assert a.model_dump(exclude={"request_id"}) != b.model_dump(
        exclude={"request_id"}), (a, b)


@pytest.fixture
def plugin_client() -> Iterator[WorkerClient]:
    w = WorkerClient(REPO / "worker", prelude="Worker")
    try:
        w.start()
        assert w.execute(PLUGIN_QUERY, cell_id="plugin").status == "ok"
        yield w
    finally:
        w.kill()
        w.shutdown()


def test_extension_expression_is_queryable_without_commit(
        plugin_client: WorkerClient) -> None:
    complete = plugin_client.complete("pluginName", len("pluginName"))
    assert isinstance(complete, CompleteOk), complete
    assert complete.matches == ["pluginName"], complete

    inspect = plugin_client.inspect("pluginName", 0)
    assert isinstance(inspect, InspectOk), inspect
    assert inspect.found and inspect.hover == "plugin-value", inspect
