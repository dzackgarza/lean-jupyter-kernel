"""Build identity and provenance across the real adapter/worker boundary.

Obligations, each against real processes:

1. the bare worker reports the authored `release.toml` contract plus its exact
   build commit, in both `ready` and `describe`;
2. the installed kernelspec publishes the compared provenance over the real
   `nbdsl_provenance` comm — keyed on the opener's comm_id — including the
   hash of the binary it executed;
3. a static contract disagreement refuses cells, typed;
4. a commit disagreement on a dirty tree does NOT refuse: it is reported as
   `unverifiable-dirty`, because a dirty tree's commit identifies nothing;
5. missing build identity is a typed error from a LIVE kernel, never a death
   before kernel_info.

(3)-(5) need identities the working tree cannot produce on demand. The seam is
`NBDSL_BUILD_INFO`: the documented env var the adapter reads its own build
identity from at startup. Each test copies the authoritative
`_build_info.json` to a scratch file, changes one field, and points a real
kernel at the copy. Everything else — the kernel, the worker, the comparison —
is production code; the authoritative file is never touched. The one case a
dirty checkout cannot stage at all (two CLEAN artifacts disagreeing) exercises
the real decision function directly.

Run: .venv/bin/pytest nbdsl_kernel/tests/test_identity.py   (after install.py)
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any, Iterator

import pytest
from jupyter_client.manager import start_new_kernel

from nbdsl_kernel.protocol import BuildInfo, compare

# roundtrip.py's frame codec is the repo's independent oracle for the wire
# protocol — deliberately not nbdsl_kernel.worker's. Reuse it here for the
# same reason: these assertions must not be able to agree with a broken
# adapter simply because both sides share one implementation.
from roundtrip import Worker as BareWorker
from test_e2e import _send_comm, run_cell

REPO = Path(__file__).resolve().parents[2]
WORKER_EXE = REPO / "worker/.lake/build/bin/nbdsl_worker"
BUILD_INFO = REPO / "nbdsl_kernel/nbdsl_kernel/_build_info.json"

COMMIT = re.compile(r"[0-9a-f]{40}")


@pytest.fixture(scope="module")
def release() -> dict[str, Any]:
    raw: dict[str, Any] = tomllib.loads((REPO / "release.toml").read_text())
    return raw


def test_worker_reports_authored_contract_and_commit(
        release: dict[str, Any]) -> None:
    """`ready` and `describe` both carry the identity, and it is the one
    release.toml authorizes."""
    expected = {
        "release": release["release"]["version"],
        "plugin_api": release["compat"]["plugin_api"],
        "wire": release["compat"]["wire_protocol"],
        "toolchain": release["toolchain"]["lean"],
        "mathlib": release["toolchain"]["mathlib"],
    }
    w = BareWorker(prelude="Init")  # mathlib-free: identity needs no prelude
    try:
        ready = w.replies.read_frame()
        describe = w.request("describe")
    finally:
        w.shutdown()

    for frame, name in ((ready, "ready"), (describe, "describe")):
        assert {k: frame.get(k) for k in expected} == expected, (name, frame)
        assert COMMIT.fullmatch(frame.get("commit", "")), (name, frame)
        assert isinstance(frame.get("dirty"), bool), (name, frame)
        # Not merely well-shaped: a commit that actually exists here. (Not
        # necessarily HEAD — a binary may predate an unrelated commit.)
        assert subprocess.run(
            ["git", "-C", str(REPO), "cat-file", "-t", frame["commit"]],
            capture_output=True, text=True).stdout.strip() == "commit", frame
    # The wire version has one owner now: the literal is gone from Worker.lean.
    assert ready["protocol"] == release["compat"]["wire_protocol"], ready
    assert ready["commit"] == describe["commit"], (ready, describe)


def test_provenance_comm_publishes_the_executed_pair() -> None:
    """The installed kernelspec answers `nbdsl_provenance` with the compared
    identities and the hash of the worker binary it actually ran."""
    km, kc = start_new_kernel(kernel_name="nbdsl", startup_timeout=60)
    try:
        reply, _ = run_cell(kc, "#eval 1 + 1")  # start the worker for real
        assert reply["status"] == "ok", reply
        _send_comm(kc, "comm_open", {"comm_id": "prov-1",
                                     "target_name": "nbdsl_provenance",
                                     "data": {}})
        prov = _await_comm(kc, "prov-1")
    finally:
        kc.stop_channels()
        km.shutdown_kernel(now=True)

    # Clean pair: True. Dev tree: the commit cannot identify the sources.
    assert prov["agreed"] in (True, "unverifiable-dirty"), prov
    adapter, worker = prov["adapter"], prov["worker"]
    for field in ("release", "plugin_api", "wire", "toolchain"):
        assert adapter[field] == worker[field], (field, prov)
    # The commit is only required to match when the pair was actually
    # verified. Asserting it unconditionally would fail for the right reason
    # in CI and the wrong one here: an unverifiable-dirty pair is allowed to
    # straddle a commit, which is the whole reason that state exists.
    if prov["agreed"] is True:
        assert adapter["commit"] == worker["commit"], prov
    assert COMMIT.fullmatch(worker["commit"]), prov
    with WORKER_EXE.open("rb") as f:
        assert prov["worker_binary_sha256"] == \
            hashlib.file_digest(f, "sha256").hexdigest(), prov


def _kernel_with_build_info(path: Path) -> tuple[Any, Any]:
    return start_new_kernel(kernel_name="nbdsl", startup_timeout=60,
                            env={**os.environ, "NBDSL_BUILD_INFO": str(path)})


def test_static_contract_mismatch_refuses_cells(tmp_path: Path) -> None:
    """A contract field disagreement always refuses — typed, naming both
    identities. These are projections of release.toml, so disagreement is a
    real incompatibility however either side was built."""
    info = json.loads(BUILD_INFO.read_text())
    scratch = tmp_path / "_build_info.json"
    scratch.write_text(json.dumps({**info, "release": "0.0.1-wrong"}))

    km, kc = _kernel_with_build_info(scratch)
    try:
        reply, outputs = run_cell(kc, "#eval 1 + 1")
        assert reply["status"] == "error", reply
        assert reply["ename"] == "ProvenanceError", reply
        assert "release" in reply["evalue"], reply
        assert "0.0.1-wrong" in reply["evalue"], reply     # the adapter's
        assert info["release"] in reply["evalue"], reply   # and the worker's
        assert any(m["msg_type"] == "error" for m in outputs), outputs
    finally:
        kc.stop_channels()
        km.shutdown_kernel(now=True)


def test_commit_mismatch_on_a_dirty_tree_still_runs(tmp_path: Path) -> None:
    """A dirty tree's commit is not an identity — the source no longer matches
    what it names — so it can neither confirm nor deny agreement and is
    reported rather than enforced. Two CLEAN commits disagreeing is the case
    that refuses; see test_clean_trees_must_agree_on_the_commit."""
    info = json.loads(BUILD_INFO.read_text())
    scratch = tmp_path / "_build_info.json"
    scratch.write_text(json.dumps({**info, "commit": "0" * 40, "dirty": True}))

    km, kc = _kernel_with_build_info(scratch)
    try:
        reply, _ = run_cell(kc, "#eval 1 + 1")
        assert reply["status"] == "ok", reply
        _send_comm(kc, "comm_open", {"comm_id": "prov-dirty",
                                     "target_name": "nbdsl_provenance",
                                     "data": {}})
        prov = _await_comm(kc, "prov-dirty")
        assert prov["agreed"] == "unverifiable-dirty", prov
        assert prov["adapter"]["commit"] == "0" * 40, prov
        assert prov["adapter"]["dirty"] is True, prov
        assert prov["worker"]["commit"] != "0" * 40, prov
    finally:
        kc.stop_channels()
        km.shutdown_kernel(now=True)


def test_missing_build_info_is_typed_not_a_dead_kernel(tmp_path: Path) -> None:
    """The kernel must START and answer, then refuse every cell with a typed
    error. Dying before kernel_info only produces "Kernel died before replying
    to kernel_info", which names neither the cause nor the fix."""
    missing = tmp_path / "absent" / "_build_info.json"
    km, kc = _kernel_with_build_info(missing)
    try:
        assert kc.is_alive()
        reply, _ = run_cell(kc, "#eval 1 + 1")
        assert reply["status"] == "error", reply
        assert reply["ename"] == "ProvenanceError", reply
        assert str(missing) in reply["evalue"], reply
    finally:
        kc.stop_channels()
        km.shutdown_kernel(now=True)


def test_clean_trees_must_agree_on_the_commit() -> None:
    """The release/CI case, which a dirty working tree cannot exhibit: two
    clean artifacts from different commits are refused. Exercises the real
    decision function on real identities, not a re-implementation of it."""
    base = BuildInfo.model_validate_json(BUILD_INFO.read_text())
    clean = base.model_copy(update={"dirty": False})
    other = clean.model_copy(update={"commit": "b" * 40})
    assert compare(clean, clean) == ([], True)
    assert compare(clean, other) == (["commit"], False)
    # …and the same pair, either side dirty, is unverifiable rather than wrong.
    assert compare(clean.model_copy(update={"dirty": True}), other) == \
        ([], "unverifiable-dirty")


def test_a_dirty_tree_suspends_only_the_commit_comparison() -> None:
    """`dirty` withdraws the COMMIT evidence, never the contract check: the
    static fields are projections of release.toml and disagree for real
    however either side was built. Guards the reordering that would answer
    "unverifiable-dirty" before looking at STATIC at all — which the other
    tests here cannot catch, because they inherit `dirty` from the
    authoritative build info (true in a dev tree, false in CI)."""
    base = BuildInfo.model_validate_json(BUILD_INFO.read_text())
    dirty = base.model_copy(update={"dirty": True})
    assert compare(dirty, dirty.model_copy(update={"wire": 99})) == \
        (["wire"], False)


def _build_identity(clone: Path) -> BuildInfo:
    """Build the adapter wheel in `clone` and read the identity it embedded."""
    # Not check=True: CalledProcessError with captured output reports only the
    # exit status, and the build's own diagnostic is the thing worth reading.
    proc = subprocess.run([sys.executable, "-m", "build", "--wheel",
                           str(clone / "nbdsl_kernel")],
                          capture_output=True, text=True, cwd=clone)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return BuildInfo.model_validate_json(
        (clone / "nbdsl_kernel/nbdsl_kernel/_build_info.json").read_text())


def test_an_installers_own_droppings_do_not_make_the_source_dirty(
        tmp_path: Path) -> None:
    """`dirty` must mean the SOURCE differs from the commit, not that some
    tool wrote a file into the checkout — package managers do exactly that:
    `uv pip install git+…` leaves an untracked `.ok` sentinel, which made
    every uv-installed adapter report dirty and so permanently disabled the
    strict clean-pair commit comparison for the documented consumer install
    path. A real modification must still be caught."""
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "--quiet", f"file://{REPO}", str(clone)],
                   check=True, capture_output=True)

    (clone / ".ok").write_text("")               # uv's real sentinel, verbatim
    (clone / "stray-tool-output.log").write_text("noise")
    assert _build_identity(clone).dirty is False

    tracked = clone / "nbdsl_kernel/nbdsl_kernel/kernel.py"
    tracked.write_text(tracked.read_text() + "\n# a real source change\n")
    assert _build_identity(clone).dirty is True


def test_building_refreshes_both_halves_into_a_matched_pair() -> None:
    """The atomic-rebuild property `just build` exists to provide.

    The worker re-embeds its identity on every build, while an editable
    install keeps the `_build_info.json` it was installed with — so refreshing
    one half alone strands the session behind a refusal that describes the
    build workflow rather than any real incompatibility. Running the two steps
    the `build` recipe runs must leave a pair the real decision function
    accepts. Mathlib-free: the worker package is its own project, and identity
    needs no prelude.
    """
    subprocess.run(["lake", "build", "nbdsl_worker"], cwd=REPO / "worker",
                   check=True, capture_output=True)
    subprocess.run([sys.executable, str(REPO / "scripts/sync_build_info.py")],
                   check=True, capture_output=True)

    w = BareWorker(prelude="Init")
    try:
        ready = w.replies.read_frame()
    finally:
        w.shutdown()

    adapter = BuildInfo.model_validate_json(BUILD_INFO.read_text())
    worker = BuildInfo.model_validate(ready)
    disagree, agreed = compare(adapter, worker)
    assert disagree == [], (disagree, adapter, worker)
    # True on a clean tree, "unverifiable-dirty" on a dev one — never a
    # refusal, which is the property under test.
    assert agreed is not False, (agreed, adapter, worker)
    assert adapter.commit == worker.commit, (adapter, worker)


def _await_comm(kc: Any, comm_id: str, timeout: float = 30) -> dict[str, Any]:
    while True:
        msg = kc.get_iopub_msg(timeout=timeout)
        if (msg["msg_type"] == "comm_msg"
                and msg["content"].get("comm_id") == comm_id):
            data: dict[str, Any] = msg["content"]["data"]
            return data
