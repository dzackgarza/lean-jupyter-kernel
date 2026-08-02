#!/usr/bin/env python3
"""Kernel-owned semantic conformance: one law set, many plugin profiles.

Every law in the full matrix is proven through the ordinary Jupyter protocol
against an installed kernelspec — `execute`, `complete`, `inspect`, a real
`interrupt_request`, and a real SIGKILL of the worker process group. The
focused `atomicity` journey uses only `execute` and a real
`interrupt_request`, because completion, inspection, recovery, and transport
are separate journeys. Claims about Jupyter semantics are never made from
direct kernel or helper calls. The one addition is
`output-control-separated`, which ALSO decodes the worker's frames with the
INDEPENDENT oracle codec in nbdsl_kernel/tests/roundtrip.py: proving plugin
output never becomes control traffic needs a decoder that is not production's,
or a codec bug would pass both sides.

A profile is DATA ONLY (plugin selection, commands, cancellation point,
expected MIME types, canonical projections, and the shape of the plugin's
registration). It cannot supply law code, expected success booleans, or result
overrides; `load_profile` rejects any key that would.

Usage:
    python3 conformance/runner.py conformance/nbdsl.toml --journey all
    python3 conformance/runner.py conformance/nbdsl.toml --journey recovery
    python3 conformance/runner.py conformance/lean-cas-dsl.toml \\
        --journey all [--source-dir DIR] [--kernel-name NAME] \\
        [--output result.json]

Exit status is 0 only when every law passes, 1 on a law failure, 2 when the
profile or the environment it names is unusable.

Resource contract: at most ONE mathlib-loaded worker is alive at any moment.
The candidate session is shut down before the independent control session
starts; the laws compare observations, not simultaneity.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import queue
import signal
import subprocess
import sys
import time
import tomllib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


def _kernel_repo() -> Path:
    """The kernel repository whose identity this result reports, located by its
    authored compatibility source — never guessed."""
    for start in (Path(__file__).resolve().parent, Path.cwd().resolve()):
        for candidate in (start, *start.parents):
            if ((candidate / "release.toml").exists()
                    and (candidate / "nbdsl_kernel").is_dir()):
                return candidate
    raise RuntimeError("cannot locate the kernel repository")


REPO = _kernel_repo()
sys.path.insert(0, str(REPO / "nbdsl_kernel/tests"))

# The INDEPENDENT frame codec. roundtrip.py's docstring explains why it
# deliberately duplicates production's: sharing production's codec would let a
# codec bug pass both sides unnoticed. Do not "deduplicate" this import.
from roundtrip import FrameReader, write_frame  # noqa: E402

from jupyter_client.kernelspec import KernelSpecManager  # noqa: E402
from jupyter_client.manager import start_new_kernel  # noqa: E402
from nbdsl_kernel.worker import find_worker_exe  # noqa: E402

# The first execute of a session waits for the worker's prelude import (all of
# mathlib, from oleans); later replies get the same budget because elaboration
# is legitimately slow.
STARTUP = 900.0
QUERY_TIMEOUT = 120.0
MIN_FREE_GB = 6  # a mathlib worker is 3-4 GB; never start one into swap
CANCELLATION_STEP_LIMIT = 5000
LEAN_NUM_THREADS = "1"
CONFORMANCE_LOCK = Path(
    os.environ.get(
        "NBDSL_CONFORMANCE_LOCK",
        f"{os.environ.get('TMPDIR') or '/tmp'}"
        f"/nbdsl-conformance-{os.getuid()}.lock"))
CONFORMANCE_LOCK_TIMEOUT = 15.0

LAWS = [
    "registration-isolated",
    "success-commits",
    "error-rolls-back",
    "parse-error-rolls-back",
    "cancellation-rolls-back",
    "replay-reconstructs",
    "restart-reconstructs",
    "completion-sees-environment",
    "inspection-sees-environment",
    "output-control-separated",
]
ATOMICITY_LAWS = (
    "success-commits",
    "error-rolls-back",
    "parse-error-rolls-back",
    "cancellation-rolls-back",
)
RECOVERY_LAWS = ("restart-reconstructs", "replay-reconstructs")

# Keys that would move law authority into the data file. Fixed decision 4:
# profiles supply inputs and observations, never verdicts.
FORBIDDEN_PROFILE_KEYS = {
    "expect", "expected", "expects", "status", "verdict", "result", "results",
    "laws", "law", "override", "overrides", "skip", "skips", "xfail",
    "allow_failure", "optional", "assert", "asserts", "pass", "fail",
}

REQUIRED = {
    "profile": ["name"],
    "plugin": ["source", "commit", "package", "prelude_module", "kernel_name"],
    "registration": ["setup", "command", "shape"],
    "observation": ["command", "mimes", "projection"],
    "control": ["setup"],
    "failure": ["demo_prefix", "demo_probe", "prefix", "output", "command",
                "probe", "output_marker", "output_mime"],
    "parse_failure": ["demo_prefix", "demo_probe", "prefix", "output",
                      "command", "probe", "output_marker", "output_mime"],
    "cancellation": ["demo_prefix", "demo_probe", "prefix", "slow_header",
                     "slow_step", "slow_repeat", "slow_footer", "output",
                     "output_marker", "probe", "interrupt_after_seconds"],
    "replay": ["force", "restore"],
    "completion": ["garbage", "constant_code", "constant_cursor",
                   "constant_match", "registered_code", "registered_cursor",
                   "registered_match"],
    "inspection": ["garbage", "constant_code", "constant_cursor",
                   "constant_signature", "registered_code",
                   "registered_cursor", "registered_signature"],
    "output": ["command", "marker", "ordinary_command", "ordinary_marker",
               "rich_command", "rich_mimes", "incremental_command",
               "incremental_markers"],
}

# A registration either creates a Lean constant or lives only in a persistent
# env extension. Both shapes must be observable through standard queries: the
# worker resolves constants from the environment and probes exact plugin-owned
# expressions through the plugin's real elaborator without committing them.
# The runner falsifies the declaration in both candidate and control sessions.
SHAPES = ("constant", "extension")


class ProfileError(RuntimeError):
    """The profile or the environment it names is unusable — not a law failure."""


# --------------------------------------------------------------------------
# profile
# --------------------------------------------------------------------------

def _reject_forbidden(node: Any, path: str = "") -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key.lower() in FORBIDDEN_PROFILE_KEYS:
                raise ProfileError(
                    f"profile key {path}{key!r} would let the profile decide a "
                    "law outcome; profiles are data only")
            _reject_forbidden(value, f"{path}{key}.")
    elif isinstance(node, list):
        for item in node:
            _reject_forbidden(item, path)


def _is_pinned_commit(value: object) -> bool:
    return (isinstance(value, str)
            and len(value) == 40
            and all(c in "0123456789abcdef" for c in value))


def load_profile(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as fh:
            profile = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ProfileError(f"cannot load profile {path}: {exc}") from exc
    _reject_forbidden(profile)
    for section, keys in REQUIRED.items():
        if section not in profile:
            raise ProfileError(f"profile is missing section [{section}]")
        if not isinstance(profile[section], dict):
            raise ProfileError(f"profile section [{section}] must be a table")
        for key in keys:
            if key not in profile[section]:
                raise ProfileError(f"profile is missing {section}.{key}")
    shape = profile["registration"]["shape"]
    if shape not in SHAPES:
        raise ProfileError(
            f"registration.shape must be one of {SHAPES}, not {shape!r}")
    declared = profile["plugin"]["commit"]
    if declared != "IN-REPOSITORY" and not _is_pinned_commit(declared):
        raise ProfileError(
            "plugin.commit must be IN-REPOSITORY or a lowercase 40-hex "
            f"immutable commit, not {declared!r}")
    try:
        cancellation_steps = int(profile["cancellation"]["slow_repeat"])
    except (TypeError, ValueError) as exc:
        raise ProfileError(
            "cancellation.slow_repeat must be an integer") from exc
    if not 0 < cancellation_steps <= CANCELLATION_STEP_LIMIT:
        raise ProfileError(
            "cancellation.slow_repeat exceeds the bounded conformance "
            f"limit of {CANCELLATION_STEP_LIMIT}")
    return profile


@contextmanager
def conformance_slot() -> Iterator[None]:
    """Serialize installed conformance runs for this user.

    A profile runner can be launched by CI, a qualification script, and a
    developer at the same time. Each process's memory check is otherwise a
    race: both can observe enough RAM and then start multi-GB workers
    together, pushing the host into swap.
    """
    try:
        lock = CONFORMANCE_LOCK.open("a+")
    except OSError as exc:
        raise ProfileError(
            f"cannot open conformance resource lock {CONFORMANCE_LOCK}: {exc}"
        ) from exc
    with lock:
        deadline = time.monotonic() + CONFORMANCE_LOCK_TIMEOUT
        while True:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ProfileError(
                        "another conformance run owns the resource slot; "
                        f"refusing concurrent worker launch after "
                        f"{CONFORMANCE_LOCK_TIMEOUT:.0f}s")
                time.sleep(0.25)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def cancellation_cell(cfg: dict[str, Any]) -> str:
    """The cancellation cell: register FIRST, then elaborate a bounded flat
    term whose steps each pass a real elaboration cancellation checkpoint.
    `{i}` is the step index."""
    steps = "\n".join(cfg["slow_step"].replace("{i}", str(i))
                      for i in range(int(cfg["slow_repeat"])))
    return "\n".join([cfg["prefix"], cfg["output"], cfg["slow_header"], steps,
                      cfg["slow_footer"]])


# --------------------------------------------------------------------------
# process identity
# --------------------------------------------------------------------------

def _kernel_pid(km: Any) -> int:
    provisioner = getattr(km, "provisioner", None)
    for owner in (getattr(provisioner, "process", None), provisioner,
                  getattr(km, "kernel", None)):
        pid = getattr(owner, "pid", None)
        if isinstance(pid, int):
            return pid
    raise ProfileError("cannot determine the kernel process pid")


def _ppid_table() -> dict[int, int]:
    table: dict[int, int] = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            stat = Path(f"/proc/{entry}/stat").read_text()
        except OSError:
            continue
        # comm (field 2) is parenthesised and may itself contain spaces.
        table[int(entry)] = int(stat[stat.rindex(")") + 2:].split()[1])
    return table


def _alive(pid: int) -> bool:
    """Running, not merely present in /proc. A killed child stays visible as a
    zombie until its parent reaps it, and the adapter only reaps on its next
    execute."""
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
    """Live worker processes descended from this kernel. Descent matters: no
    other session's worker may be mistaken for this one's."""
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
    kernel_pid: int,
) -> list[tuple[int, int, str, list[int]]]:
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
    while any(_alive(pid) for pid in pids):
        if time.monotonic() >= deadline:
            survivors = [pid for pid in pids if _alive(pid)]
            raise ProfileError(f"worker processes survived SIGKILL: {survivors}")
        time.sleep(0.2)


def _free_gb() -> int:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) // (1024 * 1024)
    raise ProfileError("/proc/meminfo has no MemAvailable")


def await_memory() -> int:
    """One mathlib worker at a time, and never into swap."""
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        free = _free_gb()
        if free >= MIN_FREE_GB:
            return free
        time.sleep(15)
    raise ProfileError(
        f"only {_free_gb()} GB available after waiting; refusing to start a "
        f"mathlib worker (need {MIN_FREE_GB} GB)")


# --------------------------------------------------------------------------
# session
# --------------------------------------------------------------------------

class Session:
    """One live kernel session driven through the production Jupyter client."""

    def __init__(self, kernel_name: str) -> None:
        await_memory()
        env = os.environ.copy()
        # Mathlib-backed workers have large working sets. Keep each proof
        # session single-threaded so a serialized run does not still create
        # reclaim pressure from Lean's default host-wide task pool.
        env["LEAN_NUM_THREADS"] = LEAN_NUM_THREADS
        self.km, self.kc = start_new_kernel(kernel_name=kernel_name,
                                            startup_timeout=60, env=env)
        self.pid = _kernel_pid(self.km)
        self.comms: list[dict[str, Any]] = []

    def close(self) -> None:
        """Shut down, then make sure no mathlib worker outlived the kernel — an
        orphan holds gigabytes for the rest of the run."""
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
            await_dead([
                member
                for _, _, _, members in groups
                for member in members
            ])

    # -- messaging ---------------------------------------------------------

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
                content: dict[str, Any] = reply["content"]
                return content

    def run(self, code: str,
            timeout: float = STARTUP) -> tuple[dict[str, Any], list[Any]]:
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
        """Execute, let elaboration reach its checkpoints, then send a real
        interrupt_request through the kernel manager."""
        msg_id = self.kc.execute(code)
        try:
            self._shell(msg_id, after)
            raise ProfileError(
                "the cancellation cell returned before the interrupt; it is "
                "not a cancellation point")
        except queue.Empty:
            pass
        self.km.interrupt_kernel()
        reply = self._shell(msg_id, timeout)
        outputs = self._collect(msg_id, timeout)
        return reply, outputs

    def kill_worker(self) -> dict[str, Any]:
        """SIGKILL the real worker process group and prove it is gone."""
        before = worker_process_groups(self.pid)
        if not before:
            raise ProfileError(
                "no live worker process found under the kernel; the restart "
                "law has nothing to kill")
        killed: list[dict[str, Any]] = []
        for pid, pgid, cmd, _ in before:
            os.killpg(pgid, signal.SIGKILL)
            killed.append({"pid": pid, "pgid": pgid, "cmdline": cmd[:200]})
        await_dead([
            member
            for _, _, _, members in before
            for member in members
        ])
        return {"killed": killed}


def texts(outputs: list[Any]) -> str:
    return "".join(m["content"]["text"] for m in outputs
                   if m["msg_type"] == "stream")


def mime_bundles(outputs: list[Any]) -> list[dict[str, Any]]:
    return [m["content"]["data"] for m in outputs
            if m["msg_type"] in ("execute_result", "display_data")]


def output_matches(outputs: list[Any], cfg: dict[str, Any]) -> bool:
    visible = texts(outputs) + json.dumps(
        mime_bundles(outputs), ensure_ascii=False)
    return (cfg["output_marker"] in visible
            and any(cfg["output_mime"] in bundle
                    for bundle in mime_bundles(outputs)))


def output_leaked(outputs: list[Any], cfg: dict[str, Any]) -> bool:
    visible = texts(outputs) + json.dumps(
        mime_bundles(outputs), ensure_ascii=False)
    return (cfg["output_marker"] in visible
            or any(cfg["output_mime"] in bundle
                   for bundle in mime_bundles(outputs)))


# --------------------------------------------------------------------------
# observation
# --------------------------------------------------------------------------

def _dig(payload: Any, dotted: str) -> Any:
    node = payload
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            raise ProfileError(
                f"observation projection path {dotted!r} is missing at "
                f"{part!r}")
        node = node[part]
    return node


def _read(reply: dict[str, Any], outputs: list[Any],
          cfg: dict[str, Any]) -> dict[str, Any]:
    """The canonical projection of a plugin-authored MIME payload.

    Absence is an observation too: a command that cannot run because the
    registration is missing is exactly what discriminates the environments.
    """
    mimes: list[str] = cfg["mimes"]
    bundle = next((b for b in mime_bundles(outputs)
                   if all(m in b for m in mimes)), None)
    if reply["status"] != "ok" or bundle is None:
        return {"present": False, "status": reply["status"],
                "detail": str(reply.get("evalue", ""))[:400]}
    return {"present": True, "mimes": sorted(mimes),
            "projection": {k: _dig(bundle[mimes[0]], k)
                           for k in cfg["projection"]}}


def observe(session: Session, cfg: dict[str, Any]) -> dict[str, Any]:
    reply, outputs = session.run(cfg["command"])
    return _read(reply, outputs, cfg)


def _route(stream: str) -> str:
    """Which production recovery path the kernel reported taking."""
    if "Restored session from cache" in stream:
        return "cache"
    if "Replayed" in stream:
        return "replay"
    return "unknown"


def _recovery_trace(stream: str, reply: dict[str, Any]) -> dict[str, str]:
    """Separate the opaque execute request into the recovery phases it drove."""
    return {
        "cache_restore": (
            "restored" if "Restored session from cache" in stream
            else "timed-out" if "session cache restore timed out" in stream
            else "not-restored"
        ),
        "source_replay": (
            "replayed" if "Replayed" in stream else "not-replayed"
        ),
        "observation": str(reply.get("status", "missing-status")),
    }


def _recovery_phase(label: str, action: Callable[[], Any],
                    timings: dict[str, float]) -> Any:
    """Give every bounded Jupyter wait a failure message tied to its phase."""
    started = time.monotonic()
    try:
        result = action()
    except queue.Empty as exc:
        elapsed = time.monotonic() - started
        raise ProfileError(
            f"recovery phase {label} received no Jupyter message after "
            f"{elapsed:.1f}s") from exc
    except TimeoutError as exc:
        elapsed = time.monotonic() - started
        raise ProfileError(
            f"recovery phase {label} timed out after {elapsed:.1f}s: {exc}"
        ) from exc
    timings[label] = round(time.monotonic() - started, 3)
    return result


def query_answers(session: Session, profile: dict[str, Any]) -> dict[str, Any]:
    """What complete and inspect answer for the three probes the query laws
    need: a name that does not exist, a name the PRELUDE defines, and the name
    this profile registers."""
    comp, insp = profile["completion"], profile["inspection"]
    out: dict[str, Any] = {}
    for label, code, cursor, match in (
            ("garbage", comp["garbage"], len(comp["garbage"]), None),
            ("constant", comp["constant_code"], comp["constant_cursor"],
             comp["constant_match"]),
            ("registered", comp["registered_code"], comp["registered_cursor"],
             comp["registered_match"])):
        rep = session.complete(code, cursor)
        matches = rep.get("matches", [])
        out[f"complete_{label}"] = {
            "code": code, "cursor": cursor, "want": match,
            "found": bool(matches) if match is None else match in matches,
            "n_matches": len(matches), "sample": matches[:8]}
    for label, code, cursor, sig in (
            ("garbage", insp["garbage"], 0, None),
            ("constant", insp["constant_code"], insp["constant_cursor"],
             insp["constant_signature"]),
            ("registered", insp["registered_code"], insp["registered_cursor"],
             insp["registered_signature"])):
        rep = session.inspect(code, cursor)
        data = rep.get("data", {})
        text = json.dumps(data, ensure_ascii=False)
        out[f"inspect_{label}"] = {
            "code": code, "cursor": cursor, "want": sig,
            "reply_found": bool(rep.get("found")),
            "found": bool(rep.get("found")) if sig is None
            else bool(rep.get("found")) and sig in text,
            "data": {k: str(v)[:400] for k, v in data.items()}}
    return out


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------

class Report:
    def __init__(self, expected_laws: tuple[str, ...] = tuple(LAWS)) -> None:
        self.expected_laws = expected_laws
        self.laws: dict[str, dict[str, Any]] = {}

    def record(self, law: str, ok: bool, observation: dict[str, Any],
               detail: str) -> None:
        if law not in self.expected_laws:
            raise AssertionError(f"unknown law {law!r}")
        self.laws[law] = {"law": law, "status": "pass" if ok else "fail",
                          "observation": observation, "detail": detail}

    def ordered(self) -> list[dict[str, Any]]:
        for law in self.expected_laws:
            self.laws.setdefault(law, {"law": law, "status": "fail",
                                       "observation": {},
                                       "detail": "law did not run"})
        return [self.laws[law] for law in self.expected_laws]

    def verdict(self) -> str:
        return ("pass" if all(v["status"] == "pass" for v in self.ordered())
                else "fail")


# --------------------------------------------------------------------------
# candidate-session laws
# --------------------------------------------------------------------------

def ledger_absence(session: Session,
                   profile: dict[str, Any]) -> dict[str, Any]:
    """Failed and cancelled registrations must stay out of the ledger.

    The atomicity laws prove rollback in-session; recovery must prove those
    rolled-back names do not reappear after real worker death. The probes are
    the same ones the failure/parse/cancel laws use for the leak names — never
    the demo prefixes that were intentionally committed to prove observability.
    """
    probes = {
        "failure": profile["failure"]["probe"],
        "parse_failure": profile["parse_failure"]["probe"],
        "cancellation": profile["cancellation"]["probe"],
    }
    results: dict[str, Any] = {}
    all_absent = True
    for kind, code in probes.items():
        reply, _ = session.run(code)
        absent = reply["status"] == "error"
        results[kind] = {
            "probe": code,
            "status": reply["status"],
            "absent": absent,
            "detail": str(reply.get("evalue", ""))[:300],
        }
        all_absent = all_absent and absent
    return {"absent": all_absent, "probes": results}


def run_recovery(session: Session, profile: dict[str, Any],
                 report: Report,
                 committed: dict[str, Any]) -> dict[str, Any]:
    """Run only the two worker-death recovery laws for a targeted regression."""
    obs_cfg = profile["observation"]
    timings: dict[str, float] = {}
    before_ledger = _recovery_phase(
        "pre-restart ledger absence",
        lambda: ledger_absence(session, profile),
        timings,
    )
    if not before_ledger["absent"]:
        raise ProfileError(
            "recovery prerequisite: failed/cancelled registrations must be "
            "absent before worker death (atomicity must not re-commit them): "
            f"{before_ledger}")
    candidate_queries = _recovery_phase(
        "pre-restart queries", lambda: query_answers(session, profile), timings)

    killed = _recovery_phase("first worker kill", session.kill_worker, timings)
    reply, outputs = _recovery_phase(
        "first recovery observation",
        lambda: session.run(obs_cfg["command"]),
        timings,
    )
    stream = texts(outputs)
    after_restart = _read(reply, outputs, obs_cfg)
    queries_after_restart = _recovery_phase(
        "post-first-recovery queries",
        lambda: query_answers(session, profile),
        timings,
    )
    ledger_after_restart = _recovery_phase(
        "post-first-recovery ledger absence",
        lambda: ledger_absence(session, profile),
        timings,
    )
    report.record(
        "restart-reconstructs",
        after_restart == committed
        and queries_after_restart == candidate_queries
        and ledger_after_restart["absent"],
        {**killed, "recovery_route": _route(stream),
         "recovery_trace": _recovery_trace(stream, reply),
         "recovery_stream": stream[:400], "phase_seconds": dict(timings),
         "observation_after": after_restart,
         "queries_after_recovery": queries_after_restart,
         "ledger_absence_before": before_ledger,
         "ledger_absence": ledger_after_restart},
        "the worker process was SIGKILLed from outside the kernel and the "
        "production restart path reconstructed the committed observation and "
        "the same completion/inspection answers, without restoring "
        "failed/cancelled registrations")

    for code in profile["replay"]["force"]:
        reply, _ = _recovery_phase(
            f"cache invalidation {code!r}",
            lambda code=code: session.run(code),
            timings,
        )
        if reply["status"] != "ok":
            raise ProfileError(f"replay-forcing cell failed: {code!r} -> {reply}")
    killed = _recovery_phase("second worker kill", session.kill_worker, timings)
    reply, outputs = _recovery_phase(
        "second recovery observation",
        lambda: session.run(obs_cfg["command"]),
        timings,
    )
    stream = texts(outputs)
    after_replay = _read(reply, outputs, obs_cfg)
    queries_after_replay = _recovery_phase(
        "post-second-recovery queries",
        lambda: query_answers(session, profile),
        timings,
    )
    ledger_after_replay = _recovery_phase(
        "post-second-recovery ledger absence",
        lambda: ledger_absence(session, profile),
        timings,
    )
    route = _route(stream)
    report.record(
        "replay-reconstructs",
        route == "replay"
        and after_replay == committed
        and queries_after_replay == candidate_queries
        and ledger_after_replay["absent"],
        {**killed, "recovery_route": route, "recovery_stream": stream[:400],
         "recovery_trace": _recovery_trace(stream, reply),
         "phase_seconds": dict(timings),
         "cache_invalidated_by": profile["replay"]["force"],
         "observation_after": after_replay,
         "queries_after_recovery": queries_after_replay,
         "ledger_absence": ledger_after_replay},
        "with the session cache invalidated the worker recovered by replaying "
        "the committed sources and reconstructed the same observation and "
        "completion/inspection answers, without restoring failed/cancelled "
        "registrations")
    for code in profile["replay"]["restore"]:
        reply, outputs = _recovery_phase(
            f"cache restore {code!r}",
            lambda code=code: session.run(code),
            timings,
        )
        if reply["status"] != "ok":
            raise ProfileError(
                f"replay restore cell failed: {code!r} -> {reply}\n"
                f"{texts(outputs)[:800]}")

    return {"committed": committed, "queries": candidate_queries}


def run_candidate(session: Session, profile: dict[str, Any],
                  report: Report, *, atomicity_only: bool = False,
                  recovery_only: bool = False
                  ) -> dict[str, Any]:
    """Every law provable inside the registering environment, plus the
    observations the control session will be compared against."""
    obs_cfg = profile["observation"]

    for code in profile["registration"]["setup"]:
        reply, outputs = session.run(code)
        if reply["status"] != "ok":
            raise ProfileError(
                f"profile setup cell failed: {code!r} -> {reply}\n"
                f"{texts(outputs)[:800]}")

    # -- success-commits ---------------------------------------------------
    before = observe(session, obs_cfg)
    reply, _ = session.run(profile["registration"]["command"])
    committed = observe(session, obs_cfg)
    again = observe(session, obs_cfg)
    success_ok = (reply["status"] == "ok" and not before["present"]
                  and committed["present"] and committed == again)
    success_observation = {
        "before": before, "after": committed, "reobserved": again,
        "registration_command": profile["registration"]["command"],
        "registration_status": reply["status"],
    }
    if recovery_only:
        if not success_ok:
            raise ProfileError(
                "recovery prerequisite did not establish a committed "
                f"observation: {success_observation}")
        return run_recovery(session, profile, report, committed)
    report.record(
        "success-commits", success_ok, success_observation,
        "the discriminating command commits exactly its observation change: "
        "unobservable before, the canonical projection after, unchanged when "
        "observed again")

    # -- error-rolls-back --------------------------------------------------
    failure_cfg = profile["failure"]
    demo_reply, _ = session.run(failure_cfg["demo_prefix"])
    demo_probe_reply, _ = session.run(failure_cfg["demo_probe"])
    demo_ok = (demo_reply["status"] == "ok"
               and demo_probe_reply["status"] == "ok")
    failing_cell = "\n".join(
        [failure_cfg["prefix"], failure_cfg["output"],
         failure_cfg["command"]])
    output_reply, output_outputs = session.run(failure_cfg["output"])
    output_ready = (output_reply["status"] == "ok"
                    and output_matches(output_outputs, failure_cfg))
    reply, failure_outputs = session.run(failing_cell)
    absent_reply, _ = session.run(failure_cfg["probe"])
    after_error = observe(session, obs_cfg)
    report.record(
        "error-rolls-back",
        reply["status"] == "error"
        and absent_reply["status"] == "error"
        and demo_ok
        and output_ready
        and not output_leaked(failure_outputs, failure_cfg)
        and after_error == committed,
        {"failing_command": failing_cell,
         "failing_status": reply["status"],
         "failing_error": str(reply.get("evalue", ""))[:400],
         "output_probe_status": output_reply["status"],
         "output_probe_ready": output_ready,
         "candidate_output_published": output_leaked(
             failure_outputs, failure_cfg),
         "demo_prefix": failure_cfg["demo_prefix"],
         "demo_probe": failure_cfg["demo_probe"],
         "demo_probe_status": demo_probe_reply["status"],
         "probe": failure_cfg["probe"],
         "probe_after_failure": absent_reply["status"],
         "pre": committed, "post": after_error},
        "a failing cell discards a candidate registration whose demo "
        "prefix/probe pair independently demonstrates that registration is "
        "observable, without publishing candidate output or leaving the "
        "failed name committed")

    # -- parse-error-rolls-back ---------------------------------------------
    parse_cfg = profile["parse_failure"]
    demo_reply, _ = session.run(parse_cfg["demo_prefix"])
    demo_probe_reply, _ = session.run(parse_cfg["demo_probe"])
    demo_ok = (demo_reply["status"] == "ok"
               and demo_probe_reply["status"] == "ok")
    output_reply, output_outputs = session.run(parse_cfg["output"])
    output_ready = (output_reply["status"] == "ok"
                    and output_matches(output_outputs, parse_cfg))
    parse_cell = "\n".join(
        [parse_cfg["prefix"], parse_cfg["output"], parse_cfg["command"]])
    reply, parse_outputs = session.run(parse_cell)
    absent_reply, _ = session.run(parse_cfg["probe"])
    after_parse = observe(session, obs_cfg)
    report.record(
        "parse-error-rolls-back",
        reply["status"] == "error"
        and absent_reply["status"] == "error"
        and demo_ok
        and output_ready
        and not output_leaked(parse_outputs, parse_cfg)
        and after_parse == committed,
        {"failing_command": parse_cell,
         "failing_status": reply["status"],
         "failing_error": str(reply.get("evalue", ""))[:400],
         "output_probe_status": output_reply["status"],
         "output_probe_ready": output_ready,
         "candidate_output_published": output_leaked(
             parse_outputs, parse_cfg),
         "demo_prefix": parse_cfg["demo_prefix"],
         "demo_probe": parse_cfg["demo_probe"],
         "demo_probe_status": demo_probe_reply["status"],
         "probe": parse_cfg["probe"],
         "probe_after_failure": absent_reply["status"],
         "pre": committed, "post": after_parse},
        "a malformed tail discards a candidate registration and buffered "
        "output while preserving the committed observation, without leaving "
        "the failed name committed")

    if not atomicity_only:
        candidate_queries = query_answers(session, profile)

        # -- output-control-separated, Jupyter half ------------------------
        out_cfg = profile["output"]
        comms_before = len(session.comms)

        ordinary_reply, ordinary_outputs = session.run(
            out_cfg["ordinary_command"])
        ordinary_text = texts(ordinary_outputs)
        ordinary_followup = observe(session, obs_cfg)

        rich_reply, rich_outputs = session.run(out_cfg["rich_command"])
        rich_bundles = mime_bundles(rich_outputs)
        rich_bundle = next(
            (bundle for bundle in rich_bundles
             if all(mime in bundle for mime in out_cfg["rich_mimes"])),
            None)
        rich_followup = observe(session, obs_cfg)

        control_reply, control_outputs = session.run(out_cfg["command"])
        control_text = texts(control_outputs) + json.dumps(
            mime_bundles(control_outputs), ensure_ascii=False)
        control_followup = observe(session, obs_cfg)

        incremental_reply, incremental_outputs = session.run(
            out_cfg["incremental_command"])
        incremental_text = texts(incremental_outputs)
        incremental_followup = observe(session, obs_cfg)
        marker_positions = [
            incremental_text.find(marker)
            for marker in out_cfg["incremental_markers"]
        ]
        jupyter_half = {
            "ordinary": {
                "status": ordinary_reply["status"],
                "marker": out_cfg["ordinary_marker"],
                "text": ordinary_text[:400],
                "followup": ordinary_followup,
            },
            "rich": {
                "status": rich_reply["status"],
                "required_mimes": out_cfg["rich_mimes"],
                "bundle_present": rich_bundle is not None,
                "followup": rich_followup,
            },
            "control": {
                "status": control_reply["status"],
                "marker": out_cfg["marker"],
                "text": control_text[:400],
                "followup": control_followup,
            },
            "incremental": {
                "status": incremental_reply["status"],
                "markers": out_cfg["incremental_markers"],
                "text": incremental_text[:400],
                "marker_positions": marker_positions,
                "followup": incremental_followup,
            },
            "new_comm_messages": len(session.comms) - comms_before,
            "ok": (ordinary_reply["status"] == "ok"
                   and out_cfg["ordinary_marker"] in ordinary_text
                   and ordinary_followup == committed
                   and rich_reply["status"] == "ok"
                   and rich_bundle is not None
                   and rich_followup == committed
                   and control_reply["status"] == "ok"
                   and out_cfg["marker"] in control_text
                   and control_followup == committed
                   and incremental_reply["status"] == "ok"
                   and marker_positions == sorted(marker_positions)
                   and all(pos >= 0 for pos in marker_positions)
                   and incremental_followup == committed
                   and len(session.comms) == comms_before)}

    # -- cancellation-rolls-back -------------------------------------------
    cancel_cfg = profile["cancellation"]
    # Cooperative cancellation is a claim about the WORKER PROCESS, not the
    # reply text: the interrupt escalation path also answers `Interrupted`, but
    # only after killing the worker. Same live pid before and after is the
    # structural difference between the two.
    demo_reply, _ = session.run(cancel_cfg["demo_prefix"])
    demo_probe_reply, _ = session.run(cancel_cfg["demo_probe"])
    demo_ok = (demo_reply["status"] == "ok"
               and demo_probe_reply["status"] == "ok")
    pids_before = {pid for pid, _ in worker_processes(session.pid)}
    output_reply, output_outputs = session.run(cancel_cfg["output"])
    output_ready = (output_reply["status"] == "ok"
                    and output_matches(output_outputs, cancel_cfg))
    reply, cancellation_outputs = session.run_and_interrupt(
        cancellation_cell(cancel_cfg),
        float(cancel_cfg["interrupt_after_seconds"]))
    pids_after = {pid for pid, _ in worker_processes(session.pid)}
    probe_reply, _ = session.run(cancel_cfg["probe"])
    after_cancel = observe(session, obs_cfg)
    cooperative = (reply.get("ename") == "Interrupted"
                   and bool(pids_before) and pids_before == pids_after)
    report.record(
        "cancellation-rolls-back",
        cooperative and probe_reply["status"] == "error"
        and demo_ok
        and output_ready
        and not output_leaked(cancellation_outputs, cancel_cfg)
        and after_cancel == committed,
        {"reply_ename": reply.get("ename"),
         "reply_evalue": str(reply.get("evalue", ""))[:300],
         "cooperative": cooperative,
         "output_probe_status": output_reply["status"],
         "output_probe_ready": output_ready,
         "candidate_output_published": output_leaked(
             cancellation_outputs, cancel_cfg),
         "worker_pids_before": sorted(pids_before),
         "worker_pids_after": sorted(pids_after),
         "cancelled_registration": cancel_cfg["prefix"],
         "demo_prefix": cancel_cfg["demo_prefix"],
         "demo_probe": cancel_cfg["demo_probe"],
         "demo_probe_status": demo_probe_reply["status"],
         "probe": cancel_cfg["probe"], "probe_status": probe_reply["status"],
         "probe_detail": str(probe_reply.get("evalue", ""))[:300],
         "observation_after": after_cancel},
        "cooperative cancellation discarded a candidate registration whose "
        "demo prefix/probe pair independently proved observability, left the "
        "committed observation equal, and did not re-commit the cancelled "
        "name")

    if atomicity_only:
        return {"committed": committed}

    return run_recovery(session, profile, report, committed) | {
        "jupyter_output_half": jupyter_half}


# --------------------------------------------------------------------------
# control-session laws
# --------------------------------------------------------------------------

def run_control(session: Session, profile: dict[str, Any],
                candidate: dict[str, Any], report: Report) -> None:
    """The independent environment. It never saw the candidate's registrations,
    so anything it can observe was never candidate-local."""
    for code in profile["control"]["setup"]:
        reply, outputs = session.run(code)
        if reply["status"] != "ok":
            raise ProfileError(
                f"control setup cell failed: {code!r} -> {reply}\n"
                f"{texts(outputs)[:800]}")

    control_obs = observe(session, profile["observation"])
    report.record(
        "registration-isolated",
        candidate["committed"]["present"] and not control_obs["present"],
        {"candidate": candidate["committed"], "control": control_obs,
         "control_setup": profile["control"]["setup"]},
        "a second independent kernel session, running the same cells minus "
        "the registration, cannot make the observation the candidate commits")

    control_queries = query_answers(session, profile)
    shape = profile["registration"]["shape"]
    cand = candidate["queries"]

    for law, prefix, kind in (
            ("completion-sees-environment", "complete", "completion"),
            ("inspection-sees-environment", "inspect", "inspection")):
        # Honest discrimination first: a boundary answering the same thing for
        # a name that does not exist and for one that does is not answering
        # about the environment at all.
        garbage_ok = not (cand[f"{prefix}_garbage"]["found"]
                          or control_queries[f"{prefix}_garbage"]["found"])
        constant_ok = (cand[f"{prefix}_constant"]["found"]
                       and control_queries[f"{prefix}_constant"]["found"])
        cand_sees = cand[f"{prefix}_registered"]["found"]
        control_sees = control_queries[f"{prefix}_registered"]["found"]
        # Both constant-shaped and extension-shaped registrations must be
        # visible in the registering session and absent from the control
        # session. The worker's query surface uses environment lookup for the
        # former and a non-committing plugin expression probe for the latter.
        registered_ok = cand_sees and not control_sees
        report.record(
            law, garbage_ok and constant_ok and registered_ok,
            {"registration_shape": shape,
             "discriminates": garbage_ok and constant_ok,
             "garbage": {"candidate": cand[f"{prefix}_garbage"],
                         "control": control_queries[f"{prefix}_garbage"]},
             "constant": {"candidate": cand[f"{prefix}_constant"],
                          "control": control_queries[f"{prefix}_constant"]},
             "registered": {"candidate": cand[f"{prefix}_registered"],
                            "control": control_queries[f"{prefix}_registered"]}},
            f"{kind} discriminates (a name that does not exist is not found, a "
            "prelude constant answers with its own signature in both "
            "environments) and answers about the environment that registered "
            "the object")


# --------------------------------------------------------------------------
# output-control-separated: the independent decoder
# --------------------------------------------------------------------------

def independent_frame_check(project: Path, prelude: str,
                            out_cfg: dict[str, Any]) -> dict[str, Any]:
    """Decode the worker's real frames with roundtrip.py's oracle codec.

    Adversarial frame-shaped plugin output must arrive INSIDE an ordinary
    reply's payload and never as a frame of its own: had it been decoded as
    one, the reply stream would desynchronise and the next request's id would
    not echo.
    """
    await_memory()
    exe = find_worker_exe(project)
    if exe is None:
        raise ProfileError(
            f"no built nbdsl_worker found for external project {project}")
    req_r, req_w = os.pipe()
    rep_r, rep_w = os.pipe()
    proc = subprocess.Popen(
        ["lake", "env", str(exe), "--req-fd", str(req_r),
         "--rep-fd", str(rep_w), "--prelude-module", prelude],
        cwd=project, pass_fds=(req_r, rep_w), stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    os.close(req_r)
    os.close(rep_w)
    replies = FrameReader(rep_r)
    try:
        ready = replies.read_frame()
        write_frame(req_w, {"op": "execute", "request_id": "forge",
                            "cell_id": "forge", "code": out_cfg["command"]})
        forged = replies.read_frame()
        # The next frame must answer the NEXT request: a forged frame decoded
        # as control traffic would be read here instead.
        write_frame(req_w, {"op": "describe", "request_id": "after-forge"})
        following = replies.read_frame()
        payload = json.dumps(forged, ensure_ascii=False)
        os.close(req_w)
        rc = proc.wait(timeout=120)
        stdout, _ = proc.communicate(timeout=10)
        return {
            "ready_op": ready.get("op"),
            "forged_request_id": forged.get("request_id"),
            "forged_status": forged.get("status"),
            "marker_inside_reply_payload": out_cfg["marker"] in payload,
            "following_request_id": following.get("request_id"),
            "worker_stdout": stdout.decode(errors="replace")[:200],
            "exit_code": rc,
            "ok": (ready.get("op") == "ready"
                   and forged.get("request_id") == "forge"
                   and forged.get("status") == "ok"
                   and out_cfg["marker"] in payload
                   and following.get("request_id") == "after-forge"
                   and stdout == b"" and rc == 0)}
    finally:
        if proc.poll() is None:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            proc.wait()


# --------------------------------------------------------------------------
# identity
# --------------------------------------------------------------------------

def git_identity(root: Path) -> dict[str, Any]:
    def git(*args: str) -> str | None:
        try:
            return subprocess.run(["git", "-C", str(root), *args],
                                  capture_output=True, text=True,
                                  check=True).stdout.strip()
        except (subprocess.CalledProcessError, OSError):
            return None
    status = git("status", "--porcelain")
    return {"root": str(root), "commit": git("rev-parse", "HEAD"),
            "dirty": None if status is None else status != ""}


def release_declaration() -> dict[str, Any]:
    with (REPO / "release.toml").open("rb") as fh:
        data: dict[str, Any] = tomllib.load(fh)
        return data


def resolve_checkout(profile: dict[str, Any],
                     override: Path | None) -> dict[str, Any]:
    """Where the plugin source under test came from, and how it was chosen.

    CI points the profile's `source_env` at the frozen checkout explicitly; the
    sibling fallback is developer convenience and is recorded as such, so it
    can never be mistaken for qualification evidence.
    """
    env_name = profile["plugin"].get("source_env")
    env_value = os.environ.get(env_name) if env_name else None
    if override is not None:
        path, how = override, "--source-dir"
    elif env_value:
        path, how = Path(env_value), f"${env_name}"
    elif profile["plugin"].get("source_fallback"):
        path, how = (Path(profile["plugin"]["source_fallback"]),
                     "profile fallback (developer convenience, NOT CI evidence)")
    else:
        path, how = REPO, "this repository"
    path = path.expanduser().resolve()
    if not path.is_dir():
        raise ProfileError(f"plugin checkout {path} does not exist (via {how})")
    if profile["plugin"]["commit"] == "IN-REPOSITORY" and path != REPO.resolve():
        raise ProfileError(
            f"IN-REPOSITORY profile must use {REPO.resolve()}, not {path}")
    return {"checkout": str(path), "resolved_via": how, **git_identity(path)}


def check_kernelspec(profile: dict[str, Any], kernel_name: str,
                     project: Path) -> dict[str, Any]:
    """The kernelspec must actually drive the checkout under test."""
    try:
        spec = KernelSpecManager().get_kernel_spec(kernel_name)
    except Exception as exc:  # jupyter_client raises NoSuchKernel
        raise ProfileError(
            f"kernelspec {kernel_name!r} is not installed: {exc}") from exc
    meta = (spec.metadata or {}).get("nbdsl", {})
    spec_project = Path(meta.get("project_root", "/nonexistent")).resolve()
    if spec_project != project.resolve():
        raise ProfileError(
            f"kernelspec {kernel_name!r} runs {spec_project}, not the checkout "
            f"under test {project.resolve()}")
    try:
        project_pos = spec.argv.index("--project")
        launched_project = Path(spec.argv[project_pos + 1]).resolve()
    except (ValueError, IndexError):
        raise ProfileError(
            f"kernelspec {kernel_name!r} has no usable --project launch "
            "argument") from None
    if launched_project != project.resolve():
        raise ProfileError(
            f"kernelspec {kernel_name!r} launches {launched_project}, not "
            f"the checkout under test {project.resolve()}")
    prelude = spec.env.get("NBDSL_PRELUDE")
    if prelude != profile["plugin"]["prelude_module"]:
        raise ProfileError(
            f"kernelspec {kernel_name!r} imports prelude {prelude!r}, not the "
            f"profile's {profile['plugin']['prelude_module']!r}")
    toolchain = project / "lean-toolchain"
    return {"kernel_name": kernel_name, "project_root": str(spec_project),
            "prelude_module": prelude, "argv": list(spec.argv),
            "lean_toolchain": (toolchain.read_text().strip()
                               if toolchain.exists() else None)}


def read_provenance(session: Session) -> dict[str, Any]:
    """The runtime identity comm, when the kernel offers one. Its absence is
    recorded, not fatal: no law depends on it yet."""
    target, comm_id = "nbdsl_provenance", "conformance-provenance"

    def matches(msg: dict[str, Any]) -> bool:
        # The kernel answers on the comm_id the request opened; the target name
        # appears only in the request, so keying on it would miss the reply.
        content = msg.get("content", {})
        return (content.get("comm_id") == comm_id
                or target in json.dumps(content, default=str))

    seen = [m for m in session.comms if matches(m)]
    if not seen:
        session.kc.shell_channel.send(session.kc.session.msg(
            "comm_open", {"comm_id": comm_id, "target_name": target,
                          "data": {}}))
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not seen:
            try:
                got = session.kc.get_iopub_msg(timeout=2)
            except queue.Empty:
                continue
            if got["msg_type"].startswith("comm_"):
                session.comms.append(got)
                if matches(got):
                    seen.append(got)
    if not seen:
        return {"comm_target": target, "status": "absent",
                "detail": "the kernel opened no nbdsl_provenance comm"}
    return {"comm_target": target, "status": "present",
            "data": [m["content"].get("data") for m in seen]}


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("profile", type=Path)
    parser.add_argument(
        "--journey",
        choices=("all", "atomicity", "recovery"),
        default="all",
        help="run the full matrix or focused atomicity/recovery laws",
    )
    parser.add_argument("--source-dir", type=Path, default=None,
                        help="clean checkout of the plugin source; overrides "
                             "the profile's source_env")
    parser.add_argument("--kernel-name", default=None,
                        help="override the profile's kernelspec name")
    parser.add_argument("--output", type=Path, default=None,
                        help="write the result JSON here (default: stdout)")
    args = parser.parse_args()

    profile = load_profile(args.profile)
    source = resolve_checkout(profile, args.source_dir)
    project = (Path(source["checkout"]) / profile["plugin"]["package"]).resolve()
    kernel_name = args.kernel_name or profile["plugin"]["kernel_name"]

    declared = profile["plugin"]["commit"]
    pinned = _is_pinned_commit(declared)
    if pinned and source["commit"] != declared:
        raise ProfileError(
            f"profile pins plugin commit {declared} but {source['checkout']} "
            f"is at {source['commit']}")

    shape = profile["registration"]["shape"]
    result: dict[str, Any] = {
        "schema": 1,
        "profile": profile["profile"]["name"],
        "profile_path": str(args.profile.resolve()),
        "kernel": {**git_identity(REPO), "release": release_declaration()},
        "plugin": {"source": profile["plugin"]["source"],
                   "declared_commit": declared, "commit_pinned": pinned,
                   "observed_commit": source["commit"],
                   "observed_dirty": source["dirty"],
                   "checkout": source["checkout"],
                   "resolved_via": source["resolved_via"],
                   "package": profile["plugin"]["package"],
                   "prelude_module": profile["plugin"]["prelude_module"],
                   "registration_shape": shape},
        # Query visibility is part of the six-journey contract for both
        # constant-shaped and extension-shaped plugin registrations.
        "extension_state_visibility": (
            "supported: standard query uses a non-committing plugin "
            "expression probe" if shape == "extension"
            else "supported: standard query uses environment declarations"),
        "toolchain": check_kernelspec(profile, kernel_name, project),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }

    expected_laws = (
        ATOMICITY_LAWS if args.journey == "atomicity"
        else RECOVERY_LAWS if args.journey == "recovery"
        else tuple(LAWS))
    report = Report(expected_laws)
    try:
        with conformance_slot():
            candidate = Session(kernel_name)
            try:
                outcome = run_candidate(
                    candidate, profile, report,
                    atomicity_only=args.journey == "atomicity",
                    recovery_only=args.journey == "recovery")
                # Identity readback is metadata for the installed proof, not a
                # separate law and not a second worker session.
                result["provenance"] = read_provenance(candidate)
            finally:
                candidate.close()

            if args.journey == "all":
                # The full matrix retains the independent environment, recovery,
                # query, and frame-decoder laws for their separate journeys.
                control = Session(kernel_name)
                try:
                    run_control(control, profile, outcome, report)
                finally:
                    control.close()

                frames = independent_frame_check(
                    project, profile["plugin"]["prelude_module"],
                    profile["output"])
                jupyter = outcome["jupyter_output_half"]
                report.record(
                    "output-control-separated",
                    jupyter["ok"] and frames["ok"],
                    {"jupyter_boundary": jupyter,
                     "independent_decoder": frames},
                    "frame-shaped output stayed ordinary output at the Jupyter "
                    "boundary, and an independent frame decoder confirms it "
                    "never became a control frame on the worker transport")
    except Exception as exc:
        # Laws already proven are real observations; a failure later in the run
        # must not throw them away. Unrun laws stay failed, and so does the
        # verdict.
        result["setup_error"] = f"{type(exc).__name__}: {exc}"

    result["laws"] = report.ordered()
    result["verdict"] = report.verdict()
    result["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")

    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(text + "\n")
    else:
        print(text)
    for law in result["laws"]:
        print(f"{law['status']:>4}  {law['law']}", file=sys.stderr)
    if "setup_error" in result:
        print(f"setup error: {result['setup_error']}", file=sys.stderr)
    print(f"verdict: {result['verdict']}", file=sys.stderr)
    if "setup_error" in result:
        return 2
    return 0 if result["verdict"] == "pass" else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ProfileError as exc:
        print(f"conformance setup error: {exc}", file=sys.stderr)
        sys.exit(2)
