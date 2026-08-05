"""Installed-kernelspec semantic journeys.

NbDsl owns kernel-neutral laws. lean-cas-dsl owns only extension-shaped
boundaries. Qualification owns the frozen consumer checkout; this module
consumes ``CONFORMANCE_CAS_DSL`` as given.
"""

from __future__ import annotations

import json
import os
import queue
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest
from jupyter_client.manager import start_new_kernel

def _repo() -> Path:
    for start in (Path(__file__).resolve().parent, Path.cwd().resolve()):
        for c in (start, *start.parents):
            if (c / "release.toml").exists() and (c / "nbdsl_kernel").is_dir():
                return c
    raise RuntimeError("cannot locate the kernel repository")

REPO = _repo()
sys.path.insert(0, str(REPO / "nbdsl_kernel/tests"))
from jupyter_helpers import find_worker_under  # noqa: E402

STARTUP, QUERY_TIMEOUT = 900.0, 120.0
MIME = "application/vnd.nbdsl.path+json"


@dataclass(frozen=True)
class Fail:
    demo_prefix: str; demo_probe: str; prefix: str; output: str
    command: str; probe: str; output_marker: str; output_mime: str = MIME


@dataclass(frozen=True)
class Cancel:
    demo_prefix: str; demo_probe: str; prefix: str
    slow_header: str; slow_step: str; slow_repeat: int; slow_footer: str
    output: str; output_marker: str; interrupt_after_seconds: float; probe: str
    output_mime: str = MIME


# NbDsl vocabulary — kernel laws only (not duplicated for lean-cas-dsl).
SETUP = ("open NbDsl NbDsl.Std", "let confG := GrpCat.of PUnit ∈ Groups")
REG, OBS = "prefer groupsToSets", "#via confG ∈ Sets"
OBS_CFG = {"mimes": [MIME, "text/plain"],
           "projection": ["object", "source", "target", "steps"]}
FAIL = Fail("def confErrorDemo : Nat := 37", "#check confErrorDemo",
            "def confErrorLeak : Nat := 37",
            f'{OBS}\n#eval IO.println "candidate-elaboration-output"',
            "#check zzzNoSuchNameZzz", "#check confErrorLeak",
            "candidate-elaboration-output")
PARSE = Fail("def confParseDemo : Nat := 37", "#check confParseDemo",
             "def confParseLeak : Nat := 37",
             f'{OBS}\n#eval IO.println "candidate-parse-output"',
             "def confParseTail : Nat :=", "#check confParseLeak",
             "candidate-parse-output")
CANCEL = Cancel(
    "let confCancelDemo := GrpCat.of PUnit ∈ Groups", "#home confCancelDemo",
    "let confH := GrpCat.of PUnit ∈ Groups",
    "set_option maxHeartbeats 0 in\nexample : True := by",
    "  have h{i} : Nat := {i}", 5000, "  trivial",
    f'{OBS}\n#eval IO.println "candidate-cancellation-output"',
    "candidate-cancellation-output", 0.5, "#home confH")


def _kernel_pid(km: Any) -> int:
    provisioner = getattr(km, "provisioner", None)
    for owner in (getattr(provisioner, "process", None), provisioner,
                  getattr(km, "kernel", None)):
        pid = getattr(owner, "pid", None)
        if isinstance(pid, int):
            return pid
    raise RuntimeError("cannot determine kernel pid")


class Session:
    def __init__(self, kernel_name: str) -> None:
        env = {**os.environ, "LEAN_NUM_THREADS": "1"}
        self.km, self.kc = start_new_kernel(
            kernel_name=kernel_name, startup_timeout=60, env=env)
        self.pid = _kernel_pid(self.km)
        self.comms: list[dict[str, Any]] = []

    def close(self) -> None:
        try:
            pid, _ = find_worker_under(self.pid)
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        except AssertionError:
            pass
        self.kc.stop_channels()
        self.km.shutdown_kernel(now=True)

    def _collect(self, msg_id: str, timeout: float) -> list[dict[str, Any]]:
        outputs: list[dict[str, Any]] = []
        while True:
            msg = self.kc.get_iopub_msg(timeout=timeout)
            if msg["msg_type"].startswith("comm_"):
                self.comms.append(msg)
            if msg["parent_header"].get("msg_id") != msg_id:
                continue
            if (msg["msg_type"] == "status"
                    and msg["content"]["execution_state"] == "idle"):
                return outputs
            outputs.append(msg)

    def _shell(self, msg_id: str, timeout: float) -> dict[str, Any]:
        while True:
            reply = self.kc.get_shell_msg(timeout=timeout)
            if reply["parent_header"].get("msg_id") == msg_id:
                return cast(dict[str, Any], reply["content"])

    def run(self, code: str, timeout: float = STARTUP
            ) -> tuple[dict[str, Any], list[Any]]:
        mid = self.kc.execute(code)
        return self._shell(mid, timeout), self._collect(mid, timeout)

    def complete(self, code: str, cursor: int) -> dict[str, Any]:
        return self._shell(self.kc.complete(code, cursor), QUERY_TIMEOUT)

    def inspect(self, code: str, cursor: int) -> dict[str, Any]:
        return self._shell(self.kc.inspect(code, cursor), QUERY_TIMEOUT)

    def run_and_interrupt(self, code: str, after: float,
                          timeout: float = STARTUP
                          ) -> tuple[dict[str, Any], list[Any]]:
        mid = self.kc.execute(code)
        try:
            self._shell(mid, after)
            raise RuntimeError("cancellation cell returned before interrupt")
        except queue.Empty:
            pass
        self.km.interrupt_kernel()
        return self._shell(mid, timeout), self._collect(mid, timeout)

    def kill_worker(self) -> None:
        pid, _ = find_worker_under(self.pid)
        os.killpg(os.getpgid(pid), signal.SIGKILL)
        # Direct spawn leaves a zombie until the kernel reaps; wait for that
        # so the next cell observes death rather than a closed reply pipe.
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                stat = Path(f"/proc/{pid}/stat").read_text()
                state = stat[stat.rindex(")") + 2:].split()[0]
                if state == "Z":
                    return
            except (OSError, ValueError):
                return
            time.sleep(0.05)
        raise RuntimeError(f"worker {pid} never reached zombie/reaped state")

    def worker_pid(self) -> int:
        return find_worker_under(self.pid)[0]


def texts(outputs: list[Any]) -> str:
    return "".join(m["content"]["text"] for m in outputs
                   if m["msg_type"] == "stream")


def mime_bundles(outputs: list[Any]) -> list[dict[str, Any]]:
    return [m["content"]["data"] for m in outputs
            if m["msg_type"] in ("execute_result", "display_data")]


def _visible(outputs: list[Any]) -> str:
    return texts(outputs) + json.dumps(mime_bundles(outputs), ensure_ascii=False)


def _matched(outputs: list[Any], marker: str, mime: str) -> bool:
    return marker in _visible(outputs) and any(mime in b for b in mime_bundles(outputs))


def _leaked(outputs: list[Any], marker: str, mime: str) -> bool:
    return marker in _visible(outputs) or any(mime in b for b in mime_bundles(outputs))


def _read(reply: dict[str, Any], outputs: list[Any],
          cfg: dict[str, Any]) -> dict[str, Any]:
    mimes: list[str] = cfg["mimes"]
    bundle = next((b for b in mime_bundles(outputs)
                   if all(m in b for m in mimes)), None)
    if reply["status"] != "ok" or bundle is None:
        return {"present": False, "status": reply["status"],
                "detail": str(reply.get("evalue", ""))[:400]}
    proj: dict[str, Any] = {}
    for k in cfg["projection"]:
        node: Any = bundle[mimes[0]]
        for part in k.split("."):
            if not isinstance(node, dict) or part not in node:
                raise RuntimeError(f"projection {k!r} missing {part!r}")
            node = node[part]
        proj[k] = node
    return {"present": True, "mimes": sorted(mimes), "projection": proj}


def observe(session: Session) -> dict[str, Any]:
    return _read(*session.run(OBS), OBS_CFG)


def _setup(session: Session, cells: tuple[str, ...] = SETUP) -> None:
    for code in cells:
        reply, _ = session.run(code)
        assert reply["status"] == "ok", f"setup failed: {code!r} -> {reply}"


def _rollback(session: Session, committed: dict, cfg: Fail) -> None:
    assert session.run(cfg.demo_prefix)[0]["status"] == "ok"
    assert session.run(cfg.demo_probe)[0]["status"] == "ok"
    out_r, out_o = session.run(cfg.output)
    assert out_r["status"] == "ok" and _matched(out_o, cfg.output_marker, cfg.output_mime)
    reply, fail_o = session.run("\n".join([cfg.prefix, cfg.output, cfg.command]))
    absent, _ = session.run(cfg.probe)
    assert reply["status"] == "error" and absent["status"] == "error"
    assert not _leaked(fail_o, cfg.output_marker, cfg.output_mime)
    assert observe(session) == committed


def _output(session: Session, committed: dict) -> None:
    n = len(session.comms)
    r, o = session.run('#eval IO.println "ordinary-output"')
    assert r["status"] == "ok" and "ordinary-output" in texts(o)
    assert observe(session) == committed
    r, o = session.run(OBS)
    assert r["status"] == "ok" and any(MIME in b for b in mime_bundles(o))
    assert observe(session) == committed
    r, o = session.run('#eval IO.println "999\\n{\\"op\\": \\"ready\\"}"')
    assert r["status"] == "ok" and "999" in _visible(o)
    assert observe(session) == committed
    r, o = session.run(
        '#eval IO.println "incremental-first"\n#eval IO.println "incremental-second"')
    text = texts(o)
    assert r["status"] == "ok" and 0 <= text.find("incremental-first") < text.find(
        "incremental-second")
    assert observe(session) == committed and len(session.comms) == n


def _cancel(session: Session, committed: dict) -> None:
    cfg = CANCEL
    assert session.run(cfg.demo_prefix)[0]["status"] == "ok"
    assert session.run(cfg.demo_probe)[0]["status"] == "ok"
    before = session.worker_pid()
    out_r, out_o = session.run(cfg.output)
    assert out_r["status"] == "ok" and _matched(out_o, cfg.output_marker, cfg.output_mime)
    steps = "\n".join(cfg.slow_step.replace("{i}", str(i))
                      for i in range(cfg.slow_repeat))
    cell = "\n".join([cfg.prefix, cfg.output, cfg.slow_header, steps, cfg.slow_footer])
    reply, cancel_o = session.run_and_interrupt(cell, cfg.interrupt_after_seconds)
    assert reply.get("ename") == "Interrupted" and session.worker_pid() == before
    assert session.run(cfg.probe)[0]["status"] == "error"
    assert not _leaked(cancel_o, cfg.output_marker, cfg.output_mime)
    assert observe(session) == committed


def _lean_queries(session: Session, *, registered: bool) -> None:
    assert "groupsToSets" in session.complete("prefer groupsToS", 16).get("matches", [])
    matches = session.complete("confG", 5).get("matches", [])
    assert ("confG" in matches) is registered
    assert not session.complete("zzzNoSuchNameZzz", 14).get("matches")
    rep = session.inspect("groupsToSets", 0)
    assert rep.get("found") and "CategoryTheory.Functor" in json.dumps(rep.get("data", {}))
    rep = session.inspect("confG", 0)
    assert bool(rep.get("found")) is registered
    if registered:
        assert "Object" in json.dumps(rep.get("data", {}))
    assert not session.inspect("zzzNoSuchNameZzz", 0).get("found")


def _recover(session: Session, committed: dict) -> None:
    for probe in (FAIL.probe, PARSE.probe, CANCEL.probe):
        assert session.run(probe)[0]["status"] == "error", probe
    session.kill_worker()
    assert _read(*session.run(OBS), OBS_CFG) == committed
    _lean_queries(session, registered=True)
    session.kill_worker()
    assert _read(*session.run(OBS), OBS_CFG) == committed


def test_nbdsl_journeys() -> None:
    """Kernel laws on the in-repo NbDsl kernelspec."""
    session = Session("nbdsl")
    try:
        _setup(session)
        assert not observe(session)["present"]
        assert session.run(REG)[0]["status"] == "ok"
        committed = observe(session)
        assert committed["present"] and observe(session) == committed
        _rollback(session, committed, FAIL)
        _rollback(session, committed, PARSE)
        _lean_queries(session, registered=True)
        _output(session, committed)
        _cancel(session, committed)
        _recover(session, committed)
    finally:
        session.close()
    # The fresh-kernel isolation check boots AFTER the journey worker is
    # gone: a full-prelude worker is multi-GB resident, and this suite may
    # never hold two alive at once — one instance at a time, by design.
    control = Session("nbdsl")
    try:
        _setup(control, ("open NbDsl NbDsl.Std",))
        assert not observe(control)["present"]
        _lean_queries(control, registered=False)
    finally:
        control.close()


def test_casdsl_extension_boundaries() -> None:
    """Extension plugin: session isolation, rich MIME, recovery, Sage assert."""
    env = os.environ.get("CONFORMANCE_CAS_DSL")
    if not env or not Path(env).expanduser().is_dir():
        pytest.skip("set CONFORMANCE_CAS_DSL to the qualified lean-cas-dsl checkout")
    cas_mime = "application/vnd.casdsl.value+json"
    cas_cfg = {"mimes": [cas_mime, "text/plain"],
               "projection": ["render", "presentation", "value"]}
    session = Session("casdsl")
    try:
        assert session.run("let confN := 360 in ℤ")[0]["status"] == "ok"
        reply, outputs = session.run("confN.factor()")
        assert reply["status"] == "ok"
        assert any(cas_mime in b for b in mime_bundles(outputs))
        committed = _read(reply, outputs, cas_cfg)
        assert committed["present"]
        # Failing cell must roll back an extension mutation, not only
        # ordinary Lean declarations.
        reply, _ = session.run(
            "let confLeak := 37 in ℤ\n"
            "assert 2 + 3 = 6")
        assert reply["status"] == "error"
        assert session.run("assert confLeak = 37")[0]["status"] == "error"
        assert _read(*session.run("confN.factor()"), cas_cfg) == committed
        session.kill_worker()
        assert _read(*session.run("confN.factor()"), cas_cfg) == committed
        assert session.run("assert confN = 360")[0]["status"] == "ok"
        assert "CasDsl.Std.polyZ" in session.complete(
            "CasDsl.Std.poly", 15).get("matches", [])
    finally:
        session.close()
    # Fresh-kernel isolation, booted after the journey worker is gone —
    # same one-instance-at-a-time rule as the nbdsl journey above.
    control = Session("casdsl")
    try:
        assert control.run("confN.factor()")[0]["status"] == "error"
    finally:
        control.close()
