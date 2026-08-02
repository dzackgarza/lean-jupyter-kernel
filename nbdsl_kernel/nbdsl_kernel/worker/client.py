"""Process management and request API for one persistent nbdsl_worker."""

from __future__ import annotations

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

from ..protocol import (
    COMPLETE_REPLY,
    INSPECT_REPLY,
    IS_COMPLETE_REPLY,
    CompleteOk,
    ExecuteReply,
    InspectOk,
    IsCompleteOk,
    ReadyFrame,
    WorkerError,
)
from .cache import SessionCacheMixin
from .errors import (
    CANCEL_GRACE,
    READY_TIMEOUT,
    REPLY_TIMEOUT,
    WorkerDied,
    WorkerInterrupted,
    check_wire_protocol,
)
from .frames import FrameReader, RawFrame, process_running
from .resolve import find_worker_exe, lake_env


class WorkerClient(SessionCacheMixin):
    """One persistent nbdsl_worker process plus its replay ledger."""

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
        # Committed (cell_id, code) pairs, for restart replay.
        self.ledger: list[tuple[str, str]] = []
        # Optional session cache dir (kernel-owned): committed state is saved
        # as an olean after each REPL commit, keyed by the ledger, and loaded
        # instead of replaying on restart. Validation = key match + load
        # success; any failure is a cache miss and replay runs.
        self.cache_dir: str | None = None
        self._rid = 0
        self._pending: dict[object, RawFrame] = {}

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
            ready = ReadyFrame.model_validate(
                replies.read_frame(READY_TIMEOUT, proc.pid))
            if os.environ.get("NBDSL_SANDBOX") == "1":
                host_worker_pid = self._host_worker_pid(proc)
                ready = ReadyFrame.model_validate({
                    **ready.model_dump(),
                    "pid": host_worker_pid,
                })
            elif ready.pid != proc.pid:
                raise WorkerDied(
                    f"worker ready PID {ready.pid} does not match owned "
                    f"process {proc.pid}")
            check_wire_protocol(ready)

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
        self.replies = None

    def running(self) -> bool:
        """Whether the owned worker process is still live."""
        return (
            self.proc is not None
            and self.worker_pid is not None
            and self.proc.poll() is None
            and process_running(self.worker_pid)
        )

    def restart_and_replay(self) -> int:
        """Fresh worker, then the session cache if it matches the ledger,
        else source replay. Returns cell count replayed, or -1 on a cache
        restore (the ledger is kept — it still describes the state)."""
        self.kill()
        self.start()
        if self._try_restore_session():
            return -1
        # A timed-out cache load leaves the worker busy in `load_session`.
        # Replace it before sending source-replay requests to the main loop.
        if not self.running():
            self.start()
        # The ledger is the canonical record of committed state, so a failed
        # replay must not consume it: a worker that dies mid-replay would
        # otherwise truncate it permanently, and the NEXT restart would replay
        # the stump and report success over a half-empty environment. Cleared
        # only so execute() can rebuild it, restored on any failure.
        ledger, self.ledger = self.ledger, []
        try:
            for cell_id, code in ledger:
                rep = self.execute(code, cell_id=cell_id)
                if rep.status != "ok":
                    raise WorkerDied(
                        f"replay diverged on {cell_id}: {rep.first_error()}")
        except BaseException:
            self.ledger = ledger
            raise
        return len(ledger)

    def _write_frame(self, obj: RawFrame) -> None:
        if self.req_fd is None:
            raise WorkerDied("no request channel (worker not started)")
        payload = json.dumps(obj).encode()
        try:
            os.write(self.req_fd, str(len(payload)).encode() + b"\n" + payload)
        except OSError as e:
            raise WorkerDied(f"cannot write to worker: {e}") from e

    def _request(self, op: str, payload: RawFrame,
                 timeout: float = REPLY_TIMEOUT) -> RawFrame:
        """Transport: one framed request, one raw reply. Typed wrappers below
        are the owned API; raw dicts do not leave this class."""
        self._rid += 1
        rid = f"r{self._rid}"
        self._write_frame({"op": op, "request_id": rid, **payload})
        try:
            return self._await(rid, timeout)
        except KeyboardInterrupt:
            # Jupyter interrupt: ask the worker to cancel the in-flight
            # request; if elaboration doesn't reach a cancellation checkpoint
            # within the grace window, kill the worker (the caller restarts
            # and replays on the next execute).
            try:
                self._write_frame({"op": "cancel", "request_id": rid})
                return self._await(rid, CANCEL_GRACE)
            except (TimeoutError, KeyboardInterrupt, WorkerDied):
                self.kill()
                raise WorkerInterrupted(
                    "interrupted: worker killed (did not cancel in time)"
                ) from None

    def _await(self, rid: str, timeout: float) -> RawFrame:
        if rid in self._pending:
            return self._pending.pop(rid)
        assert self.replies is not None  # invariant: requests follow start()
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("timed out waiting for worker reply")
            assert self.worker_pid is not None
            rep = self.replies.read_frame(remaining, self.worker_pid)
            if rep.get("request_id") == rid:
                return rep
            # out-of-order reply: stash it
            self._pending[rep.get("request_id")] = rep

    def execute(self, code: str, cell_id: str = "cell") -> ExecuteReply:
        """REPL-order execute: parent is the client's current snapshot and
        the committed cell joins the replay ledger."""
        rep = ExecuteReply.model_validate(self._request(
            "execute", {"code": code, "cell_id": cell_id,
                        "parent_snapshot": self.snapshot}))
        if rep.status == "ok":
            self.snapshot = rep.snapshot
            self.ledger.append((cell_id, code))
        return rep

    def execute_at(self, code: str, cell_id: str, parent: int) -> ExecuteReply:
        """Document-order execute against an explicit parent snapshot.
        Not ledgered: document mode recovers by prefix revalidation."""
        rep = ExecuteReply.model_validate(self._request(
            "execute", {"code": code, "cell_id": cell_id,
                        "parent_snapshot": parent}))
        if rep.status == "ok":
            self.snapshot = rep.snapshot
        return rep

    def complete(self, code: str, cursor: int) -> CompleteOk | WorkerError:
        return COMPLETE_REPLY.validate_python(self._request(
            "complete", {"code": code, "cursor": cursor}, timeout=30))

    def inspect(self, code: str, cursor: int) -> InspectOk | WorkerError:
        return INSPECT_REPLY.validate_python(self._request(
            "inspect", {"code": code, "cursor": cursor}, timeout=30))

    def is_complete(self, code: str) -> IsCompleteOk | WorkerError:
        return IS_COMPLETE_REPLY.validate_python(self._request(
            "is_complete", {"code": code}, timeout=30))

    def restart_fresh(self) -> None:
        """Fresh worker with no replay (document mode rebuilds on demand)."""
        self.kill()
        self.ledger = []
        self.start()
