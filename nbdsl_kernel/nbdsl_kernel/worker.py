"""Process management and framed-JSON transport for the nbdsl worker.

Owns everything fd-shaped: pipe setup, spawning under `lake env` (so elan
resolves the project's pinned toolchain), the length-prefixed frame codec,
stdout/stderr pump threads, the replay ledger, and kill/respawn. The kernel
class never touches fds.
"""

from __future__ import annotations

import hashlib
import json
import os
import select
import signal
import subprocess
import threading
from pathlib import Path
from typing import IO, Callable

from .protocol import (COMPLETE_REPLY, INSPECT_REPLY, IS_COMPLETE_REPLY,
                       LOAD_SESSION_REPLY, SAVE_SESSION_REPLY, CompleteOk,
                       ExecuteReply, InspectOk, IsCompleteOk, LoadSessionOk,
                       ReadyFrame, SaveSessionOk, WorkerError)

RawFrame = dict[str, object]

READY_TIMEOUT = 600.0  # first prelude import loads mathlib oleans
REPLY_TIMEOUT = 3600.0  # elaboration can legitimately be slow; interrupt kills
CANCEL_GRACE = 3.0  # cooperative-cancel window before the worker is killed


class WorkerDied(RuntimeError):
    pass


def find_worker_exe(project_root: str | Path) -> Path | None:
    """The built worker binary for a Lean project — in its own build tree, or
    in a dependency's (git deps live under .lake/packages; path deps build in
    place at the directory the Lake manifest records). None if not built."""
    root = Path(project_root)
    candidates = [root / ".lake/build/bin/nbdsl_worker",
                  *root.glob(".lake/packages/*/.lake/build/bin/nbdsl_worker")]
    manifest = root / "lake-manifest.json"
    if manifest.exists():
        for pkg in json.loads(manifest.read_text()).get("packages", []):
            if pkg.get("type") == "path":
                candidates.append(
                    (root / pkg.get("dir", ".")).resolve()
                    / ".lake/build/bin/nbdsl_worker")
    return next((c for c in candidates if c.exists()), None)


class _FrameReader:
    def __init__(self, fd: int) -> None:
        self.fd = fd
        self.buf = b""

    def read_frame(self, timeout: float) -> RawFrame:
        while b"\n" not in self.buf:
            self._fill(timeout)
        line, self.buf = self.buf.split(b"\n", 1)
        n = int(line)
        while len(self.buf) < n:
            self._fill(timeout)
        payload, self.buf = self.buf[:n], self.buf[n:]
        frame: RawFrame = json.loads(payload)
        return frame

    def _fill(self, timeout: float) -> None:
        ready, _, _ = select.select([self.fd], [], [], timeout)
        if not ready:
            raise TimeoutError("timed out waiting for worker reply")
        chunk = os.read(self.fd, 65536)
        if not chunk:
            raise WorkerDied("worker closed the reply channel")
        self.buf += chunk


class WorkerClient:
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
        self.replies: _FrameReader | None = None
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

    # -- lifecycle ---------------------------------------------------------

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

    def start(self) -> ReadyFrame:
        req_r, req_w = os.pipe()
        rep_r, rep_w = os.pipe()
        worker_exe = self._worker_exe()
        self.proc = subprocess.Popen(
            self._maybe_sandbox(
                ["lake", "env", str(worker_exe),
                 "--req-fd", str(req_r), "--rep-fd", str(rep_w),
                 "--prelude-module", self.prelude], worker_exe),
            cwd=self.project_root,
            pass_fds=(req_r, rep_w),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # Own session: Jupyter's interrupt SIGINTs the kernel's process
            # group; the worker must survive it so cancellation can be
            # cooperative (a `cancel` frame) with kill only as escalation.
            start_new_session=True,
        )
        os.close(req_r)
        os.close(rep_w)
        self.req_fd = req_w
        self.replies = _FrameReader(rep_r)
        assert self.proc.stdout is not None and self.proc.stderr is not None
        for pipe, name in ((self.proc.stdout, "stdout"),
                           (self.proc.stderr, "stderr")):
            threading.Thread(target=self._pump, args=(pipe, name),
                             daemon=True).start()
        ready = ReadyFrame.model_validate(self.replies.read_frame(READY_TIMEOUT))
        self.snapshot = ready.snapshot
        return ready

    def _pump(self, pipe: IO[bytes], name: str) -> None:
        for line in iter(pipe.readline, b""):
            self.on_stream(name, line.decode(errors="replace"))
        pipe.close()

    def kill(self) -> None:
        if self.proc and self.proc.poll() is None:
            # `lake env` FORKS the worker rather than exec'ing it, so killing
            # proc.pid alone kills only the wrapper and a busy worker (e.g. an
            # interpreted infinite loop, immune to EOF) survives as a spinning
            # orphan — observed. The worker is its own session/process-group
            # leader (start_new_session), so kill the whole group.
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                self.proc.kill()
            self.proc.wait()

    def shutdown(self, timeout: float = 10) -> None:
        if self.req_fd is not None:
            try:
                os.close(self.req_fd)  # EOF → clean worker exit
            except OSError:
                pass
            self.req_fd = None
        if self.proc:
            try:
                self.proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.kill()

    def restart_and_replay(self) -> int:
        """Fresh worker, then the session cache if it matches the ledger,
        else source replay. Returns cell count replayed, or -1 on a cache
        restore (the ledger is kept — it still describes the state)."""
        self.kill()
        self.start()
        if self._try_restore_session():
            return -1
        ledger, self.ledger = self.ledger, []
        for cell_id, code in ledger:
            rep = self.execute(code, cell_id=cell_id)
            if rep.status != "ok":
                raise WorkerDied(
                    f"replay diverged on {cell_id}: {rep.first_error()}")
        return len(ledger)

    # -- session cache -----------------------------------------------------

    def _ledger_key(self) -> str:
        h = hashlib.sha256(self.prelude.encode())
        for _, code in self.ledger:
            h.update(b"\x00" + code.encode())
        return h.hexdigest()

    def save_session(self) -> None:
        """Persist committed state after a REPL commit (cheap: the olean holds
        only session-local constants + extension entries)."""
        if self.cache_dir is None:
            return
        try:
            rep = SAVE_SESSION_REPLY.validate_python(self._request(
                "save_session", {"path": str(self.cache_dir)}, timeout=60))
        except (WorkerDied, TimeoutError):
            return
        key = Path(self.cache_dir) / "key.txt"
        if isinstance(rep, SaveSessionOk) and rep.saved:
            key.write_text(self._ledger_key())
        else:
            # Uncacheable state (open scopes, syntax-valued options, …):
            # drop the key so restart falls back to replay.
            key.unlink(missing_ok=True)

    def _try_restore_session(self) -> bool:
        if self.cache_dir is None:
            return False
        key = Path(self.cache_dir) / "key.txt"
        if not key.exists() or key.read_text() != self._ledger_key():
            return False
        try:
            rep = LOAD_SESSION_REPLY.validate_python(self._request(
                "load_session", {"path": str(self.cache_dir)}, timeout=120))
        except (WorkerDied, TimeoutError):
            return False
        if not isinstance(rep, LoadSessionOk):
            return False
        self.snapshot = rep.snapshot
        return True

    # -- requests ----------------------------------------------------------

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
                raise WorkerDied(
                    "interrupted: worker killed (did not cancel in time)"
                ) from None

    def _await(self, rid: str, timeout: float) -> RawFrame:
        if rid in self._pending:
            return self._pending.pop(rid)
        assert self.replies is not None  # invariant: requests follow start()
        while True:
            rep = self.replies.read_frame(timeout)
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
