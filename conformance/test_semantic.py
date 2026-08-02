"""Semantic conformance: ten laws × two plugins via pytest.

Journeys 2–5 through the installed kernelspec. Vocabulary is frozen
dataclasses (no TOML / result JSON / provenance). One mathlib worker at a time.
"""

from __future__ import annotations

import fcntl
import json
import os
import queue
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest
from jupyter_client.kernelspec import KernelSpecManager
from jupyter_client.manager import start_new_kernel
from nbdsl_kernel.worker import find_worker_exe

def _kernel_repo() -> Path:
    for start in (Path(__file__).resolve().parent, Path.cwd().resolve()):
        for c in (start, *start.parents):
            if (c / "release.toml").exists() and (c / "nbdsl_kernel").is_dir():
                return c
    raise RuntimeError("cannot locate the kernel repository")

REPO = _kernel_repo()
sys.path.insert(0, str(REPO / "nbdsl_kernel/tests"))
from roundtrip import FrameReader, write_frame  # noqa: E402  independent oracle

STARTUP, QUERY_TIMEOUT, MIN_FREE_GB = 900.0, 120.0, 6
LEAN_NUM_THREADS = "1"
CONFORMANCE_LOCK = Path(os.environ.get(
    "NBDSL_CONFORMANCE_LOCK",
    f"{os.environ.get('TMPDIR') or '/tmp'}/nbdsl-conformance-{os.getuid()}.lock"))
CONFORMANCE_LOCK_TIMEOUT = 15.0

@dataclass(frozen=True)
class FailureVocab:
    demo_prefix: str; demo_probe: str; prefix: str; output: str
    command: str; probe: str; output_marker: str; output_mime: str

@dataclass(frozen=True)
class CancelVocab:
    demo_prefix: str; demo_probe: str; prefix: str
    slow_header: str; slow_step: str; slow_repeat: int; slow_footer: str
    output: str; output_marker: str; output_mime: str
    interrupt_after_seconds: float; probe: str

@dataclass(frozen=True)
class QueryVocab:
    garbage: str
    constant_code: str; constant_cursor: int; constant_match: str
    registered_code: str; registered_cursor: int; registered_match: str
    insp_garbage: str
    insp_constant_code: str; insp_constant_cursor: int; constant_signature: str
    insp_registered_code: str; insp_registered_cursor: int
    registered_signature: str

@dataclass(frozen=True)
class OutputVocab:
    ordinary_command: str; ordinary_marker: str
    rich_command: str; rich_mimes: tuple[str, ...]
    incremental_command: str; incremental_markers: tuple[str, ...]
    forge_command: str; forge_marker: str

@dataclass(frozen=True)
class PluginCase:
    id: str; source: str; commit: str
    source_env: str | None; source_fallback: str | None
    package: str; prelude_module: str; kernel_name: str
    registration_shape: str
    registration_setup: tuple[str, ...]; registration_command: str
    observation_command: str
    observation_mimes: tuple[str, ...]; observation_projection: tuple[str, ...]
    control_setup: tuple[str, ...]
    failure: FailureVocab; parse_failure: FailureVocab
    cancellation: CancelVocab
    replay_force: tuple[str, ...]; replay_restore: tuple[str, ...]
    queries: QueryVocab; output: OutputVocab

    def obs_cfg(self) -> dict[str, Any]:
        return {"command": self.observation_command,
                "mimes": list(self.observation_mimes),
                "projection": list(self.observation_projection)}

def _mk(t: tuple) -> PluginCase:
    (id_, source, commit, senv, sfall, package, prelude, kname, shape,
     setup, reg, obs, mimes, proj, ctrl, fail, parse, cancel,
     rforce, rrestore, queries, output) = t
    return PluginCase(
        id_, source, commit, senv, sfall, package, prelude, kname, shape,
        setup, reg, obs, mimes, proj, ctrl,
        FailureVocab(*fail), FailureVocab(*parse), CancelVocab(*cancel),
        rforce, rrestore, QueryVocab(*queries), OutputVocab(*output))

NBDLSL = _mk(('nbdsl', 'https://github.com/dzackgarza/lean-jupyter-kernel', 'IN-REPOSITORY', None, None, 'dsls/nbdsl', 'NbDsl.Notebook', 'nbdsl', 'constant', ('open NbDsl NbDsl.Std', 'let confG := GrpCat.of PUnit ∈ Groups'), 'prefer groupsToSets', '#via confG ∈ Sets', ('application/vnd.nbdsl.path+json', 'text/plain'), ('object', 'source', 'target', 'steps'), ('open NbDsl NbDsl.Std',), ('def confErrorDemo : Nat := 37', '#check confErrorDemo', 'def confErrorLeak : Nat := 37', '#via confG ∈ Sets\n#eval IO.println "candidate-elaboration-output"', '#check zzzNoSuchNameZzz', '#check confErrorLeak', 'candidate-elaboration-output', 'application/vnd.nbdsl.path+json'), ('def confParseDemo : Nat := 37', '#check confParseDemo', 'def confParseLeak : Nat := 37', '#via confG ∈ Sets\n#eval IO.println "candidate-parse-output"', 'def confParseTail : Nat :=', '#check confParseLeak', 'candidate-parse-output', 'application/vnd.nbdsl.path+json'), ('let confCancelDemo := GrpCat.of PUnit ∈ Groups', '#home confCancelDemo', 'let confH := GrpCat.of PUnit ∈ Groups', 'set_option maxHeartbeats 0 in\nexample : True := by', '  have h{i} : Nat := {i}', 5000, '  trivial', '#via confG ∈ Sets\n#eval IO.println "candidate-cancellation-output"', 'candidate-cancellation-output', 'application/vnd.nbdsl.path+json', 0.5, '#home confH'), ('section',), ('end',), ('zzzNoSuchNameZzz', 'prefer groupsToS', 16, 'groupsToSets', 'confG', 5, 'confG', 'zzzNoSuchNameZzz', 'groupsToSets', 0, 'CategoryTheory.Functor', 'confG', 0, 'Object'), ('#eval IO.println "ordinary-output"', 'ordinary-output', '#via confG ∈ Sets', ('application/vnd.nbdsl.path+json', 'text/plain'), '#eval IO.println "incremental-first"\n#eval IO.println "incremental-second"', ('incremental-first', 'incremental-second'), '#eval IO.println "999\\n{\\"op\\": \\"ready\\"}"', '999')))
LEAN_CAS_DSL = _mk(('lean-cas-dsl', 'https://github.com/dzackgarza/lean-cas-dsl', '4c6fedafccfe77af80ac632efa780e967d726c14', 'CONFORMANCE_CAS_DSL', '../lean-cas-dsl', '.', 'CasDsl.Notebook', 'casdsl', 'extension', (), 'let confN := 360 in ℤ', 'confN.factor()', ('application/vnd.casdsl.value+json', 'text/plain'), ('render', 'presentation', 'value'), (), ('let confErrorDemo := 37 in ℤ', 'assert confErrorDemo = 37', 'let confErrorLeak := 37 in ℤ', 'confN.factor()\n#eval IO.println "candidate-elaboration-output"', 'assert 2 + 3 = 6', 'assert confErrorLeak = 37', 'candidate-elaboration-output', 'application/vnd.casdsl.value+json'), ('let confParseDemo := 37 in ℤ', 'assert confParseDemo = 37', 'let confParseLeak := 37 in ℤ', 'confN.factor()\n#eval IO.println "candidate-parse-output"', 'def confParseTail : Nat :=', 'assert confParseLeak = 37', 'candidate-parse-output', 'application/vnd.casdsl.value+json'), ('let confCancelDemo := 7 in ℤ', 'assert confCancelDemo = 7', 'let confCancel := 7 in ℤ', 'set_option maxHeartbeats 0 in\nexample : True := by', '  have h{i} : Nat := {i}', 5000, '  trivial', 'confN.factor()\n#eval IO.println "candidate-cancellation-output"', 'candidate-cancellation-output', 'application/vnd.casdsl.value+json', 0.5, 'assert confCancel = 7'), ('section',), ('end',), ('zzzNoSuchNameZzz', 'CasDsl.Std.poly', 15, 'CasDsl.Std.polyZ', 'confN', 5, 'confN', 'zzzNoSuchNameZzz', 'CasDsl.Std.polyZ', 0, 'CasDsl.Obj', 'confN', 0, '360'), ('#eval IO.println "ordinary-output"', 'ordinary-output', 'confN.factor()', ('application/vnd.casdsl.value+json', 'text/plain'), '#eval IO.println "incremental-first"\n#eval IO.println "incremental-second"', ('incremental-first', 'incremental-second'), '#eval IO.println "999\\n{\\"op\\": \\"ready\\"}"', '999')))

@contextmanager
def conformance_slot() -> Iterator[None]:
    try:
        lock = CONFORMANCE_LOCK.open("a+")
    except OSError as exc:
        raise RuntimeError(f"cannot open conformance lock: {exc}") from exc
    with lock:
        deadline = time.monotonic() + CONFORMANCE_LOCK_TIMEOUT
        while True:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("another conformance run owns the slot")
                time.sleep(0.25)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

def await_memory() -> None:
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                if int(line.split()[1]) // (1024 * 1024) >= MIN_FREE_GB:
                    return
                break
        time.sleep(15)
    raise RuntimeError(f"need {MIN_FREE_GB} GB free for a mathlib worker")

def _kernel_pid(km: Any) -> int:
    provisioner = getattr(km, "provisioner", None)
    for owner in (getattr(provisioner, "process", None), provisioner,
                  getattr(km, "kernel", None)):
        pid = getattr(owner, "pid", None)
        if isinstance(pid, int):
            return pid
    raise RuntimeError("cannot determine kernel pid")

def _ppid_table() -> dict[int, int]:
    table: dict[int, int] = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            stat = Path(f"/proc/{entry}/stat").read_text()
        except OSError:
            continue
        table[int(entry)] = int(stat[stat.rindex(")") + 2:].split()[1])
    return table

def _alive(pid: int) -> bool:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return False
    return stat[stat.rindex(")") + 2:].split()[0] != "Z"

def _cmdline(pid: int) -> str:
    try:
        return (Path(f"/proc/{pid}/cmdline").read_bytes()
                .replace(b"\0", b" ").decode(errors="replace"))
    except OSError:
        return ""

def worker_processes(kernel_pid: int) -> list[tuple[int, str]]:
    table = _ppid_table()
    found = []
    for pid in table:
        ancestor = pid
        for _ in range(32):
            ancestor = table.get(ancestor, 0)
            if ancestor <= 1:
                break
            if ancestor == kernel_pid:
                cmd = _cmdline(pid)
                if "nbdsl_worker" in cmd and "--req-fd" in cmd and _alive(pid):
                    found.append((pid, cmd))
                break
    return found

def worker_process_groups(
        kernel_pid: int) -> list[tuple[int, int, str, list[int]]]:
    groups: dict[int, tuple[int, int, str, list[int]]] = {}
    for pid, cmd in worker_processes(kernel_pid):
        pgid = os.getpgid(pid)
        if pgid in groups:
            groups[pgid][3].append(pid)
        else:
            groups[pgid] = (pid, pgid, cmd, [pid])
    return list(groups.values())

def await_dead(pids: list[int], timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while any(_alive(p) for p in pids):
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"workers survived SIGKILL: {[p for p in pids if _alive(p)]}")
        time.sleep(0.2)

def cancellation_cell(cfg: CancelVocab) -> str:
    steps = "\n".join(cfg.slow_step.replace("{i}", str(i))
                      for i in range(cfg.slow_repeat))
    return "\n".join([cfg.prefix, cfg.output, cfg.slow_header, steps,
                      cfg.slow_footer])

class Session:
    def __init__(self, kernel_name: str) -> None:
        await_memory()
        env = os.environ.copy()
        env["LEAN_NUM_THREADS"] = LEAN_NUM_THREADS
        self.km, self.kc = start_new_kernel(
            kernel_name=kernel_name, startup_timeout=60, env=env)
        self.pid = _kernel_pid(self.km)
        self.comms: list[dict[str, Any]] = []

    def close(self) -> None:
        groups = worker_process_groups(self.pid)
        try:
            self.kc.stop_channels()
            self.km.shutdown_kernel(now=True)
        finally:
            for pid, pgid, _, _ in groups:
                if _alive(pid):
                    try:
                        os.killpg(pgid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        pass
            await_dead([m for _, _, _, ms in groups for m in ms])

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
        msg_id = self.kc.execute(code)
        outputs = self._collect(msg_id, timeout)
        return self._shell(msg_id, timeout), outputs

    def complete(self, code: str, cursor: int) -> dict[str, Any]:
        return self._shell(self.kc.complete(code, cursor), QUERY_TIMEOUT)

    def inspect(self, code: str, cursor: int) -> dict[str, Any]:
        return self._shell(self.kc.inspect(code, cursor), QUERY_TIMEOUT)

    def run_and_interrupt(self, code: str, after: float,
                          timeout: float = STARTUP
                          ) -> tuple[dict[str, Any], list[Any]]:
        msg_id = self.kc.execute(code)
        try:
            self._shell(msg_id, after)
            raise RuntimeError("cancellation cell returned before interrupt")
        except queue.Empty:
            pass
        self.km.interrupt_kernel()
        reply = self._shell(msg_id, timeout)
        return reply, self._collect(msg_id, timeout)

    def kill_worker(self) -> None:
        before = worker_process_groups(self.pid)
        if not before:
            raise RuntimeError("no live worker under the kernel")
        for pid, pgid, _, _ in before:
            os.killpg(pgid, signal.SIGKILL)
        await_dead([m for _, _, _, ms in before for m in ms])

def texts(outputs: list[Any]) -> str:
    return "".join(m["content"]["text"] for m in outputs
                   if m["msg_type"] == "stream")

def mime_bundles(outputs: list[Any]) -> list[dict[str, Any]]:
    return [m["content"]["data"] for m in outputs
            if m["msg_type"] in ("execute_result", "display_data")]

def _visible(outputs: list[Any]) -> str:
    return texts(outputs) + json.dumps(mime_bundles(outputs), ensure_ascii=False)

def output_matches(outputs: list[Any], cfg: FailureVocab | CancelVocab) -> bool:
    return (cfg.output_marker in _visible(outputs)
            and any(cfg.output_mime in b for b in mime_bundles(outputs)))

def output_leaked(outputs: list[Any], cfg: FailureVocab | CancelVocab) -> bool:
    return (cfg.output_marker in _visible(outputs)
            or any(cfg.output_mime in b for b in mime_bundles(outputs)))

def _dig(payload: Any, dotted: str) -> Any:
    node = payload
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            raise RuntimeError(f"projection {dotted!r} missing {part!r}")
        node = node[part]
    return node

def _read(reply: dict[str, Any], outputs: list[Any],
          cfg: dict[str, Any]) -> dict[str, Any]:
    mimes: list[str] = cfg["mimes"]
    bundle = next((b for b in mime_bundles(outputs)
                   if all(m in b for m in mimes)), None)
    if reply["status"] != "ok" or bundle is None:
        return {"present": False, "status": reply["status"],
                "detail": str(reply.get("evalue", ""))[:400]}
    return {"present": True, "mimes": sorted(mimes),
            "projection": {k: _dig(bundle[mimes[0]], k)
                           for k in cfg["projection"]}}

def observe(session: Session, case: PluginCase) -> dict[str, Any]:
    reply, outputs = session.run(case.observation_command)
    return _read(reply, outputs, case.obs_cfg())

def _route(stream: str) -> str:
    if "Restored session from cache" in stream:
        return "cache"
    if "Replayed" in stream:
        return "replay"
    return "unknown"

def query_answers(session: Session, case: PluginCase) -> dict[str, Any]:
    q = case.queries
    out: dict[str, Any] = {}
    for label, code, cursor, match in (
            ("garbage", q.garbage, len(q.garbage), None),
            ("constant", q.constant_code, q.constant_cursor, q.constant_match),
            ("registered", q.registered_code, q.registered_cursor,
             q.registered_match)):
        matches = session.complete(code, cursor).get("matches", [])
        out[f"complete_{label}"] = {
            "code": code, "cursor": cursor, "want": match,
            "found": bool(matches) if match is None else match in matches,
            "n_matches": len(matches), "sample": matches[:8]}
    for label, code, cursor, sig in (
            ("garbage", q.insp_garbage, 0, None),
            ("constant", q.insp_constant_code, q.insp_constant_cursor,
             q.constant_signature),
            ("registered", q.insp_registered_code, q.insp_registered_cursor,
             q.registered_signature)):
        rep = session.inspect(code, cursor)
        data = rep.get("data", {})
        text = json.dumps(data, ensure_ascii=False)
        out[f"inspect_{label}"] = {
            "code": code, "cursor": cursor, "want": sig,
            "reply_found": bool(rep.get("found")),
            "found": (bool(rep.get("found")) if sig is None
                      else bool(rep.get("found")) and sig in text),
            "data": {k: str(v)[:400] for k, v in data.items()}}
    return out

def ledger_absence(session: Session, case: PluginCase) -> dict[str, Any]:
    probes = {"failure": case.failure.probe,
              "parse_failure": case.parse_failure.probe,
              "cancellation": case.cancellation.probe}
    results: dict[str, Any] = {}
    all_absent = True
    for kind, code in probes.items():
        reply, _ = session.run(code)
        absent = reply["status"] == "error"
        results[kind] = {"probe": code, "status": reply["status"],
                         "absent": absent,
                         "detail": str(reply.get("evalue", ""))[:300]}
        all_absent = all_absent and absent
    return {"absent": all_absent, "probes": results}

def independent_frame_check(project: Path, prelude: str,
                            out: OutputVocab) -> dict[str, Any]:
    await_memory()
    exe = find_worker_exe(project)
    if exe is None:
        raise RuntimeError(f"no built nbdsl_worker for {project}")
    req_r, req_w = os.pipe()
    rep_r, rep_w = os.pipe()
    proc = subprocess.Popen(
        ["lake", "env", str(exe), "--req-fd", str(req_r),
         "--rep-fd", str(rep_w), "--prelude-module", prelude],
        cwd=project, pass_fds=(req_r, rep_w), stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    os.close(req_r); os.close(rep_w)
    replies = FrameReader(rep_r)
    try:
        ready = replies.read_frame()
        write_frame(req_w, {"op": "execute", "request_id": "forge",
                            "cell_id": "forge", "code": out.forge_command})
        forged = replies.read_frame()
        write_frame(req_w, {"op": "describe", "request_id": "after-forge"})
        following = replies.read_frame()
        payload = json.dumps(forged, ensure_ascii=False)
        os.close(req_w)
        rc = proc.wait(timeout=120)
        stdout, _ = proc.communicate(timeout=10)
        return {
            "ok": (ready.get("op") == "ready"
                   and forged.get("request_id") == "forge"
                   and forged.get("status") == "ok"
                   and out.forge_marker in payload
                   and following.get("request_id") == "after-forge"
                   and stdout == b"" and rc == 0),
            "ready_op": ready.get("op"),
            "forged_request_id": forged.get("request_id"),
            "forged_status": forged.get("status"),
            "marker_inside_reply_payload": out.forge_marker in payload,
            "following_request_id": following.get("request_id"),
            "exit_code": rc,
        }
    finally:
        if proc.poll() is None:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            proc.wait()

def _git_head(root: Path) -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return None

def resolve_checkout(case: PluginCase) -> Path:
    if case.commit == "IN-REPOSITORY":
        return REPO
    env_value = os.environ.get(case.source_env) if case.source_env else None
    if env_value:
        path = Path(env_value).expanduser().resolve()
    elif case.source_fallback:
        path = (REPO / case.source_fallback).resolve()
    else:
        raise RuntimeError(f"{case.id}: no checkout configured")
    if not path.is_dir():
        raise RuntimeError(f"{case.id}: checkout missing: {path}")
    if len(case.commit) == 40 and _git_head(path) != case.commit:
        raise RuntimeError(
            f"{case.id}: expected {case.commit}, got {_git_head(path)}")
    return path

def project_root(case: PluginCase) -> Path:
    return (resolve_checkout(case) / case.package).resolve()

def check_kernelspec(case: PluginCase, project: Path) -> None:
    try:
        spec = KernelSpecManager().get_kernel_spec(case.kernel_name)
    except Exception as exc:
        raise RuntimeError(
            f"kernelspec {case.kernel_name!r} not installed: {exc}") from exc
    meta = (spec.metadata or {}).get("nbdsl", {})
    spec_project = Path(meta.get("project_root", "/nonexistent")).resolve()
    if spec_project != project.resolve():
        raise RuntimeError(f"kernelspec runs {spec_project}, not {project}")
    try:
        pos = spec.argv.index("--project")
        launched = Path(spec.argv[pos + 1]).resolve()
    except (ValueError, IndexError) as exc:
        raise RuntimeError(f"kernelspec {case.kernel_name!r} has no --project") from exc
    if launched != project.resolve():
        raise RuntimeError(f"kernelspec launches {launched}, not {project}")
    if spec.env.get("NBDSL_PRELUDE") != case.prelude_module:
        raise RuntimeError(
            f"prelude {spec.env.get('NBDSL_PRELUDE')!r} != "
            f"{case.prelude_module!r}")

def _cas_available() -> bool:
    env = os.environ.get("CONFORMANCE_CAS_DSL")
    if env and Path(env).expanduser().is_dir():
        return True
    return (REPO / "../lean-cas-dsl").resolve().is_dir()

def _require_case(case: PluginCase) -> Path:
    if case.id == "lean-cas-dsl" and not _cas_available():
        pytest.skip("lean-cas-dsl missing "
                    "(set CONFORMANCE_CAS_DSL or ../lean-cas-dsl)")
    project = project_root(case)
    check_kernelspec(case, project)
    return project

def _setup(session: Session, cells: tuple[str, ...]) -> None:
    for code in cells:
        reply, outputs = session.run(code)
        assert reply["status"] == "ok", (
            f"setup failed: {code!r} -> {reply}\n{texts(outputs)[:800]}")

def _assert_rollback(session: Session, case: PluginCase, committed: dict,
                     cfg: FailureVocab) -> None:
    demo_r, _ = session.run(cfg.demo_prefix)
    demo_p, _ = session.run(cfg.demo_probe)
    assert demo_r["status"] == "ok" and demo_p["status"] == "ok"
    out_r, out_o = session.run(cfg.output)
    assert out_r["status"] == "ok" and output_matches(out_o, cfg)
    cell = "\n".join([cfg.prefix, cfg.output, cfg.command])
    reply, fail_o = session.run(cell)
    absent, _ = session.run(cfg.probe)
    after = observe(session, case)
    assert reply["status"] == "error" and absent["status"] == "error"
    assert not output_leaked(fail_o, cfg)
    assert after == committed, {"pre": committed, "post": after}

def _jupyter_output_half(session: Session, case: PluginCase,
                         committed: dict) -> None:
    out = case.output
    n_comms = len(session.comms)
    r, o = session.run(out.ordinary_command)
    assert r["status"] == "ok" and out.ordinary_marker in texts(o)
    assert observe(session, case) == committed
    r, o = session.run(out.rich_command)
    bundle = next((b for b in mime_bundles(o)
                   if all(m in b for m in out.rich_mimes)), None)
    assert r["status"] == "ok" and bundle is not None
    assert observe(session, case) == committed
    r, o = session.run(out.forge_command)
    assert r["status"] == "ok" and out.forge_marker in _visible(o)
    assert observe(session, case) == committed
    r, o = session.run(out.incremental_command)
    text = texts(o)
    pos = [text.find(m) for m in out.incremental_markers]
    assert r["status"] == "ok" and pos == sorted(pos) and all(p >= 0 for p in pos)
    assert observe(session, case) == committed
    assert len(session.comms) == n_comms

def _assert_cancellation(session: Session, case: PluginCase,
                         committed: dict) -> None:
    cfg = case.cancellation
    demo_r, _ = session.run(cfg.demo_prefix)
    demo_p, _ = session.run(cfg.demo_probe)
    assert demo_r["status"] == "ok" and demo_p["status"] == "ok"
    before = {pid for pid, _ in worker_processes(session.pid)}
    out_r, out_o = session.run(cfg.output)
    assert out_r["status"] == "ok" and output_matches(out_o, cfg)
    reply, cancel_o = session.run_and_interrupt(
        cancellation_cell(cfg), cfg.interrupt_after_seconds)
    after_pids = {pid for pid, _ in worker_processes(session.pid)}
    probe, _ = session.run(cfg.probe)
    after = observe(session, case)
    assert (reply.get("ename") == "Interrupted"
            and bool(before) and before == after_pids), {
        "ename": reply.get("ename"), "before": sorted(before),
        "after": sorted(after_pids)}
    assert probe["status"] == "error"
    assert not output_leaked(cancel_o, cfg)
    assert after == committed

def _assert_recovery(session: Session, case: PluginCase,
                     committed: dict, queries: dict) -> None:
    assert ledger_absence(session, case)["absent"]
    session.kill_worker()
    reply, outputs = session.run(case.observation_command)
    assert _read(reply, outputs, case.obs_cfg()) == committed
    assert query_answers(session, case) == queries
    assert ledger_absence(session, case)["absent"]

    for code in case.replay_force:
        reply, _ = session.run(code)
        assert reply["status"] == "ok", f"replay force failed: {code!r}"
    session.kill_worker()
    reply, outputs = session.run(case.observation_command)
    stream = texts(outputs)
    assert _route(stream) == "replay", stream[:400]
    assert _read(reply, outputs, case.obs_cfg()) == committed
    assert query_answers(session, case) == queries
    assert ledger_absence(session, case)["absent"]
    for code in case.replay_restore:
        reply, outputs = session.run(code)
        assert reply["status"] == "ok", (
            f"replay restore failed: {code!r}\n{texts(outputs)[:800]}")

@pytest.mark.parametrize("case", [NBDLSL, LEAN_CAS_DSL], ids=lambda c: c.id)
def test_candidate_matrix(case: PluginCase) -> None:
    """success / error / parse / output-jupyter / cancel / restart / replay."""
    _require_case(case)
    with conformance_slot():
        session = Session(case.kernel_name)
        try:
            _setup(session, case.registration_setup)
            before = observe(session, case)
            reply, _ = session.run(case.registration_command)
            committed = observe(session, case)
            again = observe(session, case)
            assert reply["status"] == "ok"
            assert not before["present"]
            assert committed["present"] and committed == again

            _assert_rollback(session, case, committed, case.failure)
            _assert_rollback(session, case, committed, case.parse_failure)
            queries = query_answers(session, case)
            _jupyter_output_half(session, case, committed)
            _assert_cancellation(session, case, committed)
            _assert_recovery(session, case, committed, queries)
        finally:
            session.close()

@pytest.mark.parametrize("case", [NBDLSL, LEAN_CAS_DSL], ids=lambda c: c.id)
def test_control(case: PluginCase) -> None:
    """registration-isolated + completion/inspection environment laws."""
    _require_case(case)
    with conformance_slot():
        candidate = Session(case.kernel_name)
        try:
            _setup(candidate, case.registration_setup)
            reply, _ = candidate.run(case.registration_command)
            assert reply["status"] == "ok"
            committed = observe(candidate, case)
            assert committed["present"]
            cand_q = query_answers(candidate, case)
        finally:
            candidate.close()

        control = Session(case.kernel_name)
        try:
            _setup(control, case.control_setup)
            assert committed["present"] and not observe(control, case)["present"]
            ctrl_q = query_answers(control, case)
            for prefix in ("complete", "inspect"):
                garbage_ok = not (cand_q[f"{prefix}_garbage"]["found"]
                                  or ctrl_q[f"{prefix}_garbage"]["found"])
                constant_ok = (cand_q[f"{prefix}_constant"]["found"]
                               and ctrl_q[f"{prefix}_constant"]["found"])
                registered_ok = (cand_q[f"{prefix}_registered"]["found"]
                                 and not ctrl_q[f"{prefix}_registered"]["found"])
                assert garbage_ok and constant_ok and registered_ok, {
                    "law": prefix,
                    "c": {k: cand_q[f"{prefix}_{k}"]
                          for k in ("garbage", "constant", "registered")},
                    "k": {k: ctrl_q[f"{prefix}_{k}"]
                          for k in ("garbage", "constant", "registered")},
                }
        finally:
            control.close()

@pytest.mark.parametrize("case", [NBDLSL, LEAN_CAS_DSL], ids=lambda c: c.id)
def test_output_frame_check(case: PluginCase) -> None:
    """output-control-separated independent decoder half."""
    project = _require_case(case)
    with conformance_slot():
        frames = independent_frame_check(
            project, case.prelude_module, case.output)
        assert frames["ok"], frames
