"""Process management and request API for one persistent nbdsl_worker."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from contextlib import ExitStack, suppress
from pathlib import Path
from typing import IO

import psutil
from pydantic import ValidationError

from ..protocol import (
    COMPLETE_REPLY,
    SESSION_POLICY,
    WIRE_PROTOCOL,
    INSPECT_REPLY,
    IS_COMPLETE_REPLY,
    CompleteOk,
    ExecuteReply,
    InspectOk,
    IsCompleteOk,
    ReadyFrame,
    WorkerError,
)
from .errors import (
    CANCEL_GRACE,
    READY_TIMEOUT,
    REPLY_TIMEOUT,
    WorkerDied,
    WireProtocolError,
    WorkerInterrupted,
    check_wire_protocol,
)
from .frames import FrameReader, RawFrame, process_running
from .resolve import find_worker_exe, lake_env


class WorkerClient:
    """One negotiated process. Snapshots are scoped to its fresh nonce."""

    def __init__(self, project_root: str | Path,
                 prelude: str = "NbDsl.Notebook",
                 on_stream: Callable[[str, str], None] | None = None) -> None:
        self.project_root = Path(project_root)
        self.prelude = prelude
        self.on_stream: Callable[[str, str], None] = \
            on_stream or (lambda name, text: None)
        self.proc: subprocess.Popen[bytes] | None = None
        self.req_fd: int | None = None
        self.replies: FrameReader | None = None
        self._request_pipe: IO[bytes] | None = None
        self._reply_pipe: IO[bytes] | None = None
        self._pump_threads: list[threading.Thread] = []
        #: Host PID of the worker process (equal to `self.proc.pid` except
        #: under Bubblewrap's PID namespace).
        self.worker_pid: int | None = None
        self.snapshot = 0
        self.worker_nonce: str | None = None
        self.profile_sha256: str | None = None
        self._seen_nonces: set[str] = set()
        self._rid = 0
        self._pending: dict[str, RawFrame] = {}
        self._outstanding: set[str] = set()
        self._uncertain: set[str] = set()

    def require_session(self) -> None:
        if not self.running():
            raise WorkerDied("unavailable/worker_absent")
        if self.worker_nonce is None or self.profile_sha256 is None:
            raise WireProtocolError("unavailable/incompatible_protocol: no acknowledged session")

    @staticmethod
    def _expected_profile(env: dict[str, str]) -> str:
        """Normalize the configured availability sets, without selecting any operation."""
        explicit = env.get("NBDSL_REALIZATION_PROFILE_SHA256")
        if explicit is not None:
            if len(explicit) != 64 or any(c not in "0123456789abcdef" for c in explicit):
                raise WireProtocolError("unavailable/incompatible_protocol: invalid configured profile hash")
            return explicit
        def compact(value: object) -> str:
            return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        path = env.get("CAS_REALIZATION_PROFILE")
        if path is None:
            normalized = {"format": "cas-realization-profile/1", "id": "all",
                          "default": "all", "rules": []}
        else:
            # The worker separately checks the complete profile against published declarations.
            # This calculation only verifies the byte identity of its normalized configuration.
            with Path(path).open(encoding="utf-8") as stream:
                normalized = json.load(stream)
            for rule in normalized["rules"]:
                primitives = rule["primitive_registrations"]
                if primitives["mode"] == "only":
                    for entry in primitives["entries"]:
                        if entry.get("preferredRoutes") == []:
                            del entry["preferredRoutes"]
                    primitives["entries"].sort(key=compact)
                derivations = rule["derivations"]
                if derivations["mode"] == "only":
                    derivations["ids"].sort(key=compact)
            normalized["rules"].sort(key=lambda rule: compact(rule["target"]))
        return hashlib.sha256(compact(normalized).encode()).hexdigest()

    def _maybe_sandbox(self, cmd: list[str], worker_exe: Path) -> list[str]:
        """NBDSL_SANDBOX=1: run the worker under bubblewrap — project and
        toolchain read-only, private /tmp, no network, no foreign pids, dies
        with the kernel. A process boundary is not a security sandbox; this
        OS-level allowlist is what makes untrusted notebooks tolerable.
        ponytail: filesystem/net/pid isolation only; add resource limits
        (systemd-run -p MemoryMax=…) if runaway memory becomes a problem."""
        if os.environ.get("NBDSL_SANDBOX") != "1":
            return cmd
        home = str(Path.home())
        wrapped = [
            "bwrap",
            "--ro-bind", "/usr", "/usr",
            "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
            "--symlink", "usr/bin", "/bin", "--symlink", "usr/bin", "/sbin",
            "--ro-bind-try", "/etc/alternatives", "/etc/alternatives",
            "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
            "--ro-bind", str(self.project_root), str(self.project_root),
            "--ro-bind", f"{home}/.elan", f"{home}/.elan",
        ]
        # A path-dependency worker package lives outside the project root
        # (exe = <pkg>/.lake/build/bin/nbdsl_worker) — bind it read-only too.
        pkg_root = worker_exe.parents[3]
        if not pkg_root.is_relative_to(self.project_root):
            wrapped += ["--ro-bind", str(pkg_root), str(pkg_root)]
        return wrapped + [
            "--setenv", "HOME", home,
            "--unshare-net", "--unshare-pid",
            "--die-with-parent",
        ] + cmd

    def _worker_exe(self) -> Path:
        exe = find_worker_exe(self.project_root)
        if exe is None:
            raise WorkerDied(
                f"nbdsl_worker not built for {self.project_root}; run "
                "`lake build nbdsl_worker` there")
        return exe

    @staticmethod
    def _terminate_process_group(
            proc: subprocess.Popen[bytes],
            pump_threads: list[threading.Thread]) -> None:
        # ProcessLookupError: the group is already gone (expected race).
        with suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        for thread in pump_threads:
            thread.join()

    @staticmethod
    def _host_worker_pid(proc: subprocess.Popen[bytes]) -> int:
        """Resolve the host-visible worker when Bubblewrap owns a PID namespace."""
        try:
            root = psutil.Process(proc.pid)
            processes = [root, *root.children(recursive=True)]
            candidates = [
                process.pid for process in processes
                if os.getpgid(process.pid) == proc.pid
                and Path(process.exe()).name == "nbdsl_worker"
            ]
        except (psutil.NoSuchProcess, ProcessLookupError) as e:
            raise WorkerDied(
                f"worker process tree under sandbox {proc.pid} exited "
                "before host PID ownership could be established") from e
        if len(candidates) != 1:
            raise WorkerDied(
                f"expected exactly one host nbdsl_worker in process group "
                f"{proc.pid}, found {candidates}")
        return candidates[0]

    def start(self) -> ReadyFrame:
        assert (self.proc is None and self.req_fd is None
                and self.replies is None and self._request_pipe is None
                and self._reply_pipe is None)
        worker_exe = self._worker_exe().resolve()
        env = lake_env(self.project_root)
        with ExitStack() as cleanup:
            req_r_fd, req_w_fd = os.pipe()
            rep_r_fd, rep_w_fd = os.pipe()
            req_r = cleanup.enter_context(os.fdopen(req_r_fd, "rb", buffering=0))
            req_w = cleanup.enter_context(os.fdopen(req_w_fd, "wb", buffering=0))
            rep_r = cleanup.enter_context(os.fdopen(rep_r_fd, "rb", buffering=0))
            rep_w = cleanup.enter_context(os.fdopen(rep_w_fd, "wb", buffering=0))
            cmd = [
                str(worker_exe),
                "--req-fd", str(req_r.fileno()),
                "--rep-fd", str(rep_w.fileno()),
                "--prelude-module", self.prelude,
            ]
            proc = subprocess.Popen(
                self._maybe_sandbox(cmd, worker_exe),
                cwd=self.project_root,
                env=env,
                pass_fds=(req_r.fileno(), rep_w.fileno()),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                # Own session: Jupyter's interrupt SIGINTs the kernel's process
                # group; the worker survives so cancellation is cooperative.
                start_new_session=True,
            )
            pump_threads: list[threading.Thread] = []
            cleanup.callback(
                self._terminate_process_group, proc, pump_threads)
            req_r.close()
            rep_w.close()
            assert proc.stdout is not None and proc.stderr is not None
            for pipe, name in ((proc.stdout, "stdout"),
                               (proc.stderr, "stderr")):
                thread = threading.Thread(
                    target=self._pump, args=(pipe, name), daemon=True)
                pump_threads.append(thread)
                thread.start()

            replies = FrameReader(rep_r.fileno())
            try:
                ready = ReadyFrame.model_validate(replies.read_frame(READY_TIMEOUT, proc.pid))
            except ValidationError as e:
                raise WireProtocolError("unavailable/incompatible_protocol: malformed ready frame") from e
            if os.environ.get("NBDSL_SANDBOX") == "1":
                host_worker_pid = self._host_worker_pid(proc)
                ready = ready.model_copy(update={"pid": host_worker_pid})
            elif ready.pid != proc.pid:
                raise WorkerDied(
                    f"worker ready PID {ready.pid} does not match owned "
                    f"process {proc.pid}")
            check_wire_protocol(ready, self._expected_profile(env))
            assert ready.worker_nonce is not None and ready.realization_profile is not None
            if ready.worker_nonce in self._seen_nonces:
                raise WireProtocolError("unavailable/incompatible_protocol: reused worker nonce")
            hello: RawFrame = {"op": "hello", "protocol": WIRE_PROTOCOL,
                               "worker_nonce": ready.worker_nonce,
                               "session_policy": SESSION_POLICY}
            self._write_to(req_w.fileno(), hello)
            ack = replies.read_frame(READY_TIMEOUT, proc.pid)
            if ack != {**hello, "status": "ok"}:
                raise WireProtocolError("unavailable/incompatible_protocol: hello was not acknowledged")
            self.worker_nonce = ready.worker_nonce
            self.profile_sha256 = ready.realization_profile.sha256
            self._seen_nonces.add(ready.worker_nonce)
            self._rid = 0
            self._pending.clear()
            self._outstanding.clear()
            self._uncertain.clear()

            self.proc = proc
            self._request_pipe = req_w
            self._reply_pipe = rep_r
            self.req_fd = req_w.fileno()
            self.replies = replies
            self.worker_pid = ready.pid
            self._pump_threads = pump_threads
            self.snapshot = ready.snapshot
            cleanup.pop_all()
        return ready

    def _pump(self, pipe: IO[bytes], name: str) -> None:
        for line in iter(pipe.readline, b""):
            self.on_stream(name, line.decode(errors="replace"))
        pipe.close()

    def _close_channels(self) -> None:
        if self._request_pipe is not None:
            self._request_pipe.close()
        if self._reply_pipe is not None:
            self._reply_pipe.close()
        self._request_pipe = None
        self._reply_pipe = None
        self.req_fd = None
        self.replies = None
        self.worker_nonce = None
        self.profile_sha256 = None
        self._pending.clear()
        self._outstanding.clear()
        self._uncertain.clear()

    def kill(self) -> None:
        if self.proc is not None:
            self._terminate_process_group(self.proc, self._pump_threads)
        self.worker_pid = None
        self.proc = None
        self._pump_threads = []
        self._close_channels()

    def shutdown(self, timeout: float = 10) -> None:
        if self._request_pipe is not None:
            self._request_pipe.close()
            self._request_pipe = None
            self.req_fd = None
        if self.proc is not None:
            try:
                self.proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.kill()
                return
            for thread in self._pump_threads:
                thread.join()
        self.proc = None
        self.worker_pid = None
        self._pump_threads = []
        if self._reply_pipe is not None:
            self._reply_pipe.close()
            self._reply_pipe = None
        self._close_channels()

    def running(self) -> bool:
        """Whether the owned worker process is still live."""
        return (
            self.proc is not None
            and self.worker_pid is not None
            and self.proc.poll() is None
            and process_running(self.worker_pid)
        )

    def restart_and_replay(self) -> int:
        raise WireProtocolError("cas_no_replay forbids restoring a previous session")

    @staticmethod
    def _write_to(fd: int, obj: RawFrame) -> None:
        payload = json.dumps(obj, ensure_ascii=False).encode()
        frame = memoryview(str(len(payload)).encode() + bytes([10]) + payload)
        try:
            while frame:
                count = os.write(fd, frame)
                if count == 0:
                    raise WorkerDied("unavailable/connection_lost_after_send")
                frame = frame[count:]
        except OSError as e:
            raise WorkerDied(f"unavailable/connection_lost_after_send: {e}") from e

    def _write_frame(self, obj: RawFrame) -> None:
        self.require_session()
        assert self.req_fd is not None
        self._write_to(self.req_fd, obj)

    def _send(self, op: str, payload: RawFrame) -> str:
        self.require_session()
        self._rid += 1
        rid = f"r{self._rid}"
        self._outstanding.add(rid)
        self._write_frame({"op": op, "protocol": WIRE_PROTOCOL,
                           "worker_nonce": self.worker_nonce, "request_id": rid, **payload})
        return rid

    def _request(self, op: str, payload: RawFrame,
                 timeout: float = REPLY_TIMEOUT) -> RawFrame:
        rid = self._send(op, payload)
        try:
            return self._await(rid, timeout)
        except KeyboardInterrupt:
            if op != "execute":
                raise
            try:
                cancel = self._send("cancel", {"target_request_id": rid, "mode": "cooperative"})
                ack = self._await(cancel, CANCEL_GRACE)
                if ack.get("status") not in {"cancelled", "already_committed"}:
                    raise WorkerInterrupted(f"unavailable/cancel_unacknowledged: {ack}")
                return self._await(rid, CANCEL_GRACE)
            except (TimeoutError, KeyboardInterrupt) as e:
                self._uncertain.add(rid)
                raise WorkerInterrupted("unavailable/cancel_unacknowledged: execution indeterminate") from e
        except TimeoutError as e:
            self._uncertain.add(rid)
            raise WorkerInterrupted("unavailable/connection_lost_after_send: reply timeout; execution indeterminate") from e

    def _await(self, rid: str, timeout: float) -> RawFrame:
        if rid in self._pending:
            self._outstanding.discard(rid)
            return self._pending.pop(rid)
        assert self.replies is not None
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("timed out waiting for worker reply")
            assert self.worker_pid is not None
            rep = self.replies.read_frame(remaining, self.worker_pid)
            if rep.get("worker_nonce") != self.worker_nonce:
                raise WireProtocolError("unavailable/incompatible_protocol: reply has another worker nonce")
            if rep.get("op") == "protocol_error" and rep.get("reason") == "duplicate_request_id":
                # This source-free diagnostic is not the original request's reply.
                self.on_stream("stderr", f"duplicate request id: {rep.get('offending_request_id')}" + chr(10))
                continue
            key = rep.get("request_id")
            if not isinstance(key, str) or key not in self._outstanding or key in self._pending:
                raise WireProtocolError("worker returned an unknown or repeated response")
            if key == rid:
                self._outstanding.discard(rid)
                return rep
            self._pending[key] = rep

    def execute(self, code: str, cell_id: str = "cell") -> ExecuteReply:
        return self.execute_at(code, cell_id, self.snapshot)

    def execute_at(self, code: str, cell_id: str, parent: int) -> ExecuteReply:
        self.require_session()
        if self._uncertain:
            raise WorkerInterrupted("unavailable/indeterminate_execution: previous request must be resolved")
        try:
            rep = ExecuteReply.model_validate(self._request(
                "execute", {"code": code, "cell_id": cell_id,
                            "session_policy": SESSION_POLICY,
                            "parent_snapshot": str(parent)}))
        except ValidationError as e:
            raise WireProtocolError("malformed execution reply") from e
        if rep.parent_snapshot != parent:
            raise WireProtocolError("execution reply has a different parent")
        if rep.status == "ok":
            assert rep.commit is not None
            if rep.commit.profile_sha256 != self.profile_sha256:
                raise WireProtocolError("execution reply has a different frozen profile")
            self.snapshot = rep.snapshot
        return rep

    def complete(self, code: str, cursor: int) -> CompleteOk | WorkerError:
        return COMPLETE_REPLY.validate_python(self._request(
            "complete", {"mode": "environment", "snapshot": str(self.snapshot),
                         "code": code, "cursor": cursor}, timeout=30))

    def inspect(self, code: str, cursor: int, detail_level: int = 0) -> InspectOk | WorkerError:
        return INSPECT_REPLY.validate_python(self._request(
            "inspect", {"mode": "environment", "snapshot": str(self.snapshot),
                        "code": code, "cursor": cursor, "detail_level": detail_level}, timeout=30))

    def is_complete(self, code: str) -> IsCompleteOk | WorkerError:
        return IS_COMPLETE_REPLY.validate_python(self._request(
            "is_complete", {"mode": "syntax", "snapshot": str(self.snapshot),
                            "code": code}, timeout=30))

    def restart_fresh(self) -> None:
        """An explicit new session has no relationship to the previous snapshot IDs."""
        self.kill()
        self.start()
