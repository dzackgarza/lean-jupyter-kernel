#!/usr/bin/env python3
"""Kernel-owned semantic conformance runner (issue #3).

One invocation identifies a plugin package and prelude module through a
profile; this runner owns the LAWS and the profile owns only the vocabulary
that discriminates them. A profile carries commands and expected
observations — never assertion logic, never a law.

    python3 conformance/runner.py conformance/nbdsl.toml

The laws are the semantics the core silently relies on (docs/plugins.md):
registration lands in the Environment, a success commits exactly its change,
a failure commits nothing, cancellation discards, replay and restart
reconstruct, control frames stay separate from plugin output, and
completion/inspection see the environment this session actually built.

Two transports, because the laws live at two boundaries:

  * the framed worker transport (this file decodes frames with the
    independent oracle in nbdsl_kernel/tests/roundtrip.py, NOT with
    production's codec — a codec bug must not pass both sides);
  * the real Jupyter kernel, for the laws production owns (worker death,
    restart, replay, session cache).

Each law prints the plausible breakage it detects, so a passing run is a
fault model and not a green tick.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "nbdsl_kernel/tests"))

# The INDEPENDENT frame codec (see the module docstring in roundtrip.py: it
# deliberately duplicates production's). Reusing it here keeps this runner's
# decoding independent of nbdsl_kernel/worker.py, which is the property
# "independently decoded framed control messages" asks for.
from roundtrip import FrameReader, write_frame  # noqa: E402

TIMEOUT = 600.0  # a first prelude import pulls the plugin's whole olean set


class Failure(Exception):
    """A law was violated. The message names the law and what it observed."""


def check(ok: bool, law: str, detail: object = "") -> None:
    if not ok:
        raise Failure(f"{law}: {detail}")


def law(name: str, detects: str) -> None:
    print(f"ok: {name}\n    detects: {detects}")


# --- the framed worker transport -----------------------------------------


class Worker:
    """A worker process for one plugin profile, spoken to over framed fds."""

    def __init__(self, project: Path, prelude: str) -> None:
        req_r, req_w = os.pipe()
        rep_r, rep_w = os.pipe()
        # The worker binary comes from the PLUGIN's own dependency tree, the
        # way production resolves it — an external plugin's clean checkout
        # builds its own, and must not silently borrow this repo's.
        from nbdsl_kernel.worker import find_worker_exe
        exe = find_worker_exe(project)
        check(exe is not None,
              f"worker binary for {project} (run `lake build nbdsl_worker` there)",
              project)
        self.proc = subprocess.Popen(
            ["lake", "env", str(exe),
             "--req-fd", str(req_r), "--rep-fd", str(rep_w),
             "--prelude-module", prelude],
            cwd=project, pass_fds=(req_r, rep_w),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        os.close(req_r)
        os.close(rep_w)
        self.req_fd = req_w
        self.replies = FrameReader(rep_r)
        self._rid = 0

    def ready(self) -> dict[str, Any]:
        frame: dict[str, Any] = self.replies.read_frame()
        check(frame.get("op") == "ready", "ready handshake", frame)
        return frame

    def request(self, op: str, **fields: object) -> dict[str, Any]:
        self._rid += 1
        rid = f"c{self._rid}"
        write_frame(self.req_fd, {"op": op, "request_id": rid, **fields})
        rep: dict[str, Any] = self.replies.read_frame()
        check(rep.get("request_id") == rid, "request_id echo", rep)
        return rep

    def execute(self, code: str) -> dict[str, Any]:
        return self.request("execute", code=code, cell_id=f"cell{self._rid}")

    def snapshot(self) -> int:
        n: int = self.request("describe")["snapshot"]
        return n

    def shutdown(self) -> tuple[int, bytes]:
        os.close(self.req_fd)
        rc = self.proc.wait(timeout=TIMEOUT)
        out, _ = self.proc.communicate(timeout=10)
        return rc, out

    def kill(self) -> None:
        self.proc.kill()
        self.proc.wait(timeout=30)


def messages(rep: dict[str, Any]) -> str:
    return " ".join(d["message"] for d in rep.get("diagnostics", []))


def bundles(rep: dict[str, Any]) -> list[dict[str, Any]]:
    return [o["data"] for o in rep.get("outputs", [])]


def run_all(w: Worker, cells: list[str], label: str) -> None:
    for cell in cells:
        rep = w.execute(cell)
        check(rep["status"] == "ok", f"{label} setup", (cell, rep))


# --- the laws -------------------------------------------------------------


def law_commit(w: Worker, p: dict[str, Any]) -> None:
    """A successful command commits its exact environment change."""
    st = p["state"]
    before = w.snapshot()
    rep = w.execute(st["define"])
    check(rep["status"] == "ok", "commit", rep)
    check(rep["snapshot"] == before + 1, "commit advances the snapshot", rep)
    rep = w.execute(st["observe"])
    check(rep["status"] == "ok", "observe after commit", rep)
    check(st["observe_expect"] in messages(rep), "observe sees the commit", rep)
    law("commit-on-success",
        "a command whose environment change is discarded, or committed to a "
        "snapshot the session does not continue from")


def law_rollback(w: Worker, p: dict[str, Any]) -> None:
    """A failed command leaves exact pre/post semantic state equal."""
    st = p["state"]
    before = w.snapshot()
    rep = w.execute(st["failing"])
    check(rep["status"] == "error", "failing command must fail", rep)
    check(rep["snapshot"] == before, "failed cell keeps the parent snapshot", rep)
    check(w.snapshot() == before, "post-failure snapshot equals pre", None)
    rep = w.execute(st["observe"])
    check(rep["status"] == "ok" and st["observe_expect"] in messages(rep),
          "state intact after a failure", rep)
    law("rollback-on-error",
        "a partially-applied cell: declarations or registrations from a cell "
        "that failed later surviving into the session")


def law_registry_rollback(w: Worker, p: dict[str, Any]) -> None:
    """Plugin registry state is Environment state, so it rolls back too.

    This is the load-bearing state law (docs/plugins.md): a registration held
    in a module-level IO.Ref would survive a failed cell, and every derived
    guarantee — atomicity, replay, the session cache — would be silently wrong.

    The law observes the SAME object it registers, in both directions: absent
    after the failed cell, present after the identical registration succeeds.
    Without the second half the first is satisfied by an object that was never
    registrable at all, and the law would pass on a plugin with no registry.
    """
    reg = p["registry"]
    st = p["state"]
    run_all(w, reg["vocabulary"], "vocabulary")
    rep = w.execute(f"{reg['register']}\n{st['failing']}")
    check(rep["status"] == "error", "registration+failure cell must fail", rep)
    rep = w.execute(reg["observe_registered"])
    check(rep["status"] == "error",
          "a registration inside a failed cell must not survive it", rep)
    # …and the same observation must SUCCEED once the same registration
    # commits, or the error above proved incapacity rather than absence.
    rep = w.execute(reg["register"])
    check(rep["status"] == "ok", "the registration alone must commit", rep)
    rep = w.execute(reg["observe_registered"])
    check(rep["status"] == "ok",
          "the observation must flip once the registration commits", rep)
    law("registration-is-environment-state",
        "semantic state kept in a module-level IO.Ref instead of a persistent "
        "env extension — invisible until a rollback, replay or cache restore")


def law_structured_state(w: Worker, p: dict[str, Any]) -> None:
    """Registered state is observable as plugin-authored structured output."""
    reg = p["registry"]
    run_all(w, reg["setup"], "registry")
    rep = w.execute(reg["observe"])
    check(rep["status"] == "ok", "structured observation", rep)
    data = next((b for b in bundles(rep) if reg["mime"] in b), None)
    check(data is not None, f"structured output {reg['mime']}", rep)
    assert data is not None
    check("text/plain" in data, "structured output carries text/plain", data)
    law("structured-state-observation",
        "a status-string proxy passing for semantic proof: the assertion "
        "reads the plugin's own MIME payload, not an ok/error verdict")


def law_query_agreement(w: Worker, p: dict[str, Any]) -> None:
    """Completion and inspection expose THIS environment's objects."""
    q = p["query"]
    # a name THIS session defines, so the isolation law below has a subject
    # that provably exists here and provably does not exist elsewhere
    rep = w.execute(q["session_define"])
    check(rep["status"] == "ok", "session definition", rep)
    rep = w.request("complete", code=q["complete_code"],
                    cursor=len(q["complete_code"]))
    check(rep["status"] == "ok", "complete", rep)
    check(q["complete_expect"] in rep["matches"], "completion match", rep)
    rep = w.request("inspect", code=q["inspect_code"], cursor=0)
    check(rep["status"] == "ok" and rep["found"], "inspect", rep)
    text = f"{rep.get('type', '')} {rep.get('doc') or ''} {rep.get('hover', '')}"
    check(q["inspect_expect"] in text, "inspection content", rep)
    law("completion-and-inspection-agreement",
        "queries answered from a stale or untouched environment — the "
        "isolation law below proves the same names are absent elsewhere")


def law_control_frame_separation(w: Worker, p: dict[str, Any]) -> None:
    """Plugin output stays off the independently decoded control channel."""
    rep = w.execute(p["state"]["forge_frame"])
    check(rep["status"] == "ok", "frame-shaped output cell", rep)
    check("999" in messages(rep), "forged frame text arrived as a diagnostic", rep)
    check(w.snapshot() >= 0, "control channel still in sync", None)
    law("control-frame-separation",
        "plugin or user output written to the control fds, where a "
        "frame-shaped print would desynchronize or forge protocol traffic")


def law_cancellation(w: Worker, p: dict[str, Any]) -> None:
    """Cancellation at a real checkpoint discards candidate state.

    Plain Lean, not plugin vocabulary: every prelude is a Lean environment, and
    the checkpoints are the elaborator's own.
    """
    before = w.snapshot()
    w._rid += 1
    rid = f"c{w._rid}"
    slow = ("set_option maxHeartbeats 0 in\nexample : True := by\n"
            + "".join(f"  have h{i} : Nat := {i}\n" for i in range(25000))
            + "  trivial")
    write_frame(w.req_fd, {"op": "execute", "request_id": rid,
                           "cell_id": "conf-slow", "code": slow})
    time.sleep(1.0)
    write_frame(w.req_fd, {"op": "cancel", "request_id": rid})
    t0 = time.monotonic()
    rep = w.replies.read_frame()
    took = time.monotonic() - t0
    check(rep["request_id"] == rid and rep["status"] == "cancelled",
          "cancel reply", rep)
    check(took < 30, "cancel is cooperative, not a timeout", took)
    check(w.snapshot() == before, "cancelled work committed nothing", None)
    rep = w.execute(p["state"]["observe"])
    check(rep["status"] == "ok"
          and p["state"]["observe_expect"] in messages(rep),
          "worker alive and state intact after cancel", rep)
    law("cancellation-discards",
        "a cancelled elaboration committing partial state, or killing the "
        "worker instead of unwinding at a checkpoint")


def law_isolation(project: Path, prelude: str, p: dict[str, Any],
                  other: Worker) -> None:
    """Registration affects only the candidate environment.

    `other` has run this profile's registry setup. A second, independent
    worker on the same profile must not observe any of it: the two sessions
    share a plugin package, a prelude and a machine, and nothing else.
    """
    fresh = Worker(project, prelude)
    try:
        fresh.ready()
        # the fresh session gets the vocabulary too, so the only thing it
        # lacks is the other session's registration
        run_all(fresh, p["registry"]["vocabulary"], "fresh vocabulary")
        rep = fresh.execute(p["registry"]["observe_registered"])
        check(rep["status"] == "error",
              "an independent session must not see another's registrations", rep)
        # the same observation succeeds in the session that registered, so the
        # error above is absence and not an observation that never works
        rep = other.execute(p["registry"]["observe_registered"])
        check(rep["status"] == "ok",
              "the registering session still observes its own registration", rep)
        q = p["query"]
        rep = fresh.request("complete", code=q["session_complete_code"],
                            cursor=len(q["session_complete_code"]))
        check(q["session_complete_expect"] not in rep.get("matches", []),
              "completion must not leak a session-registered name", rep)
        # …while the session that DID register still sees it, so the check
        # above is discriminating and not just a broken second worker.
        rep = other.request("complete", code=q["session_complete_code"],
                            cursor=len(q["session_complete_code"]))
        check(q["session_complete_expect"] in rep.get("matches", []),
              "the registering session still sees its own name", rep)
    finally:
        fresh.kill()
    law("environment-isolation",
        "semantic state escaping one session — a process-global registry, or "
        "a session cache key colliding across independent sessions")


def law_stdout_clean(w: Worker) -> None:
    rc, out = w.shutdown()
    check(rc == 0, "clean shutdown", rc)
    check(out == b"", "control traffic never reaches stdout", out)
    law("transport-hygiene",
        "control frames leaking onto stdout, where a notebook would render "
        "them as plugin output")


# --- the Jupyter transport: restart, replay, session cache ----------------


def law_restart_and_replay(p: dict[str, Any]) -> None:
    """Real worker death and production restart reconstruct the session.

    Driven through the installed kernelspec, because restart, replay and the
    session cache are production's code, not this runner's.
    """
    from jupyter_client.manager import start_new_kernel

    st, reg = p["state"], p["registry"]
    km, kc = start_new_kernel(kernel_name=p["kernel_name"], startup_timeout=120)
    try:
        # the full session the framed laws built, in one production kernel
        for cell in [st["define"], *reg["vocabulary"], reg["register"],
                     *reg["setup"]]:
            reply, _ = kernel_cell(kc, cell)
            check(reply["status"] == "ok", "kernel setup", (cell, reply))
        kill_worker(km)
        reply, outputs = kernel_cell(kc, st["observe"])
        check(reply["status"] == "ok", "first cell after worker death", reply)
        text = stream_text(outputs)
        check(st["observe_expect"] in text, "state reconstructed", text)
        check("Restored session from cache." in text or "Replayed" in text,
              "recovery announced its mechanism", text)
        # The reconstruction is semantic, not textual: the plugin's registered
        # state must answer through its own structured output again.
        reply, outputs = kernel_cell(kc, reg["observe"])
        check(reply["status"] == "ok", "registry observation after restart", reply)
        check(any(reg["mime"] in m["content"].get("data", {}) for m in outputs
                  if m["msg_type"] in ("execute_result", "display_data")),
              "registered state survived the restart", [m["msg_type"] for m in outputs])
    finally:
        kc.stop_channels()
        km.shutdown_kernel(now=True)
    law("restart-and-replay",
        "a restart that loses registered plugin state, or an olean session "
        "cache that restores an environment the sources no longer describe")


def kill_worker(km: Any) -> None:
    """Kill the Lean worker under the kernel — real process death, not a flag."""
    out = subprocess.run(["pgrep", "-P", str(km.provisioner.pid), "-f",
                          "nbdsl_worker"], capture_output=True, text=True)
    pids = [int(x) for x in out.stdout.split()]
    if not pids:
        out = subprocess.run(["pgrep", "-f", "nbdsl_worker"],
                             capture_output=True, text=True)
        pids = [int(x) for x in out.stdout.split()]
    check(bool(pids), "found a worker process to kill", out.stdout)
    for pid in pids:
        os.kill(pid, 9)
    time.sleep(1.0)


def kernel_cell(kc: Any, code: str,
                timeout: float = TIMEOUT) -> tuple[dict[str, Any], list[Any]]:
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
    while True:
        reply = kc.get_shell_msg(timeout=timeout)
        if reply["parent_header"].get("msg_id") == msg_id:
            content: dict[str, Any] = reply["content"]
            return content, outputs


def stream_text(outputs: list[Any]) -> str:
    return "".join(m["content"]["text"] for m in outputs
                   if m["msg_type"] == "stream")


# --- driver ---------------------------------------------------------------


def install_kernelspec(p: dict[str, Any], project: Path) -> None:
    """Install the profile's kernelspec, so the Jupyter-transport laws drive
    the same package and prelude the framed laws did."""
    r = subprocess.run(
        [sys.executable, "-m", "nbdsl_kernel.install",
         "--project", str(project), "--name", p["kernel_name"],
         "--prelude-module", p["prelude"],
         "--display-name", f"{p['name']} conformance"],
        capture_output=True, text=True)
    check(r.returncode == 0,
          f"install kernelspec {p['kernel_name']} (is nbdsl_kernel installed "
          f"in {sys.executable}?)", r.stderr.strip() or r.stdout.strip())


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    profile = tomllib.loads(Path(sys.argv[1]).read_text())
    project = Path(os.environ.get(profile.get("project_env", ""), "")
                   or profile["project"])
    if not project.is_absolute():
        project = (REPO / project).resolve()
    check(project.is_dir(), "profile project", project)
    print(f"== conformance: {profile['name']} "
          f"({project}, prelude {profile['prelude']})")

    install_kernelspec(profile, project)
    w = Worker(project, profile["prelude"])
    ready = w.ready()
    print(f"   worker ready (lean {ready.get('lean')})")
    try:
        law_commit(w, profile)
        law_rollback(w, profile)
        law_registry_rollback(w, profile)
        law_structured_state(w, profile)
        law_query_agreement(w, profile)
        law_control_frame_separation(w, profile)
        law_cancellation(w, profile)
        law_isolation(project, profile["prelude"], profile, w)
    except BaseException:
        w.kill()
        raise
    law_stdout_clean(w)
    law_restart_and_replay(profile)
    print(f"PASS: {profile['name']} satisfies every semantic obligation")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Failure as e:
        print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)
