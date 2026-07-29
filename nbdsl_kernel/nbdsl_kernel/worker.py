"""Process management and framed-JSON transport for the nbdsl worker.

Owns everything fd-shaped: pipe setup, spawning under `lake env` (so elan
resolves the project's pinned toolchain), the length-prefixed frame codec,
stdout/stderr pump threads, the replay ledger, and kill/respawn. The kernel
class never touches fds.
"""

import json
import os
import select
import subprocess
import threading
from pathlib import Path

READY_TIMEOUT = 600.0  # first prelude import loads mathlib oleans
REPLY_TIMEOUT = 3600.0  # elaboration can legitimately be slow; interrupt kills
CANCEL_GRACE = 3.0  # cooperative-cancel window before the worker is killed


class WorkerDied(RuntimeError):
    pass


class _FrameReader:
    def __init__(self, fd):
        self.fd = fd
        self.buf = b""

    def read_frame(self, timeout):
        while b"\n" not in self.buf:
            self._fill(timeout)
        line, self.buf = self.buf.split(b"\n", 1)
        n = int(line)
        while len(self.buf) < n:
            self._fill(timeout)
        payload, self.buf = self.buf[:n], self.buf[n:]
        return json.loads(payload)

    def _fill(self, timeout):
        ready, _, _ = select.select([self.fd], [], [], timeout)
        if not ready:
            raise TimeoutError("timed out waiting for worker reply")
        chunk = os.read(self.fd, 65536)
        if not chunk:
            raise WorkerDied("worker closed the reply channel")
        self.buf += chunk


class WorkerClient:
    """One persistent nbdsl_worker process plus its replay ledger."""

    def __init__(self, project_root, prelude="NbDsl.Notebook", on_stream=None):
        self.project_root = Path(project_root)
        self.prelude = prelude
        self.on_stream = on_stream or (lambda name, text: None)
        self.proc = None
        self.req_fd = None
        self.replies = None
        self.snapshot = 0
        self.ledger = []  # committed (cell_id, code) pairs, for restart replay
        self._rid = 0
        self._pending = {}

    # -- lifecycle ---------------------------------------------------------

    def _maybe_sandbox(self, cmd):
        """NBDSL_SANDBOX=1: run the worker under bubblewrap — project and
        toolchain read-only, private /tmp, no network, no foreign pids, dies
        with the kernel. A process boundary is not a security sandbox; this
        OS-level allowlist is what makes untrusted notebooks tolerable.
        ponytail: filesystem/net/pid isolation only; add resource limits
        (systemd-run -p MemoryMax=…) if runaway memory becomes a problem."""
        if os.environ.get("NBDSL_SANDBOX") != "1":
            return cmd
        home = str(Path.home())
        return [
            "bwrap",
            "--ro-bind", "/usr", "/usr",
            "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
            "--symlink", "usr/bin", "/bin", "--symlink", "usr/bin", "/sbin",
            "--ro-bind-try", "/etc/alternatives", "/etc/alternatives",
            "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
            "--ro-bind", str(self.project_root), str(self.project_root),
            "--ro-bind", f"{home}/.elan", f"{home}/.elan",
            "--setenv", "HOME", home,
            "--unshare-net", "--unshare-pid",
            "--die-with-parent",
        ] + cmd

    def start(self):
        req_r, req_w = os.pipe()
        rep_r, rep_w = os.pipe()
        self.proc = subprocess.Popen(
            self._maybe_sandbox(
                ["lake", "env", ".lake/build/bin/nbdsl_worker",
                 "--req-fd", str(req_r), "--rep-fd", str(rep_w),
                 "--prelude-module", self.prelude]),
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
        for pipe, name in ((self.proc.stdout, "stdout"), (self.proc.stderr, "stderr")):
            threading.Thread(target=self._pump, args=(pipe, name), daemon=True).start()
        ready = self.replies.read_frame(READY_TIMEOUT)
        if ready.get("op") != "ready":
            raise WorkerDied(f"unexpected handshake: {ready}")
        self.snapshot = ready.get("snapshot", 0)
        return ready

    def _pump(self, pipe, name):
        for line in iter(pipe.readline, b""):
            self.on_stream(name, line.decode(errors="replace"))
        pipe.close()

    def kill(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()

    def shutdown(self, timeout=10):
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

    def restart_and_replay(self):
        """Fresh worker, prelude, then replay the committed ledger silently."""
        self.kill()
        self.start()
        ledger, self.ledger = self.ledger, []
        for cell_id, code in ledger:
            rep = self.execute(code, cell_id=cell_id)
            if rep.get("status") != "ok":
                raise WorkerDied(
                    f"replay diverged on {cell_id}: {rep.get('diagnostics')}")
        return len(ledger)

    # -- requests ----------------------------------------------------------

    def _write_frame(self, obj):
        payload = json.dumps(obj).encode()
        try:
            os.write(self.req_fd, str(len(payload)).encode() + b"\n" + payload)
        except (OSError, TypeError) as e:
            raise WorkerDied(f"cannot write to worker: {e}") from e

    def request(self, op, timeout=REPLY_TIMEOUT, **fields):
        self._rid += 1
        rid = f"r{self._rid}"
        self._write_frame({"op": op, "request_id": rid, **fields})
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
                    "interrupted: worker killed (did not cancel in time)") from None

    def _await(self, rid, timeout):
        if rid in self._pending:
            return self._pending.pop(rid)
        while True:
            rep = self.replies.read_frame(timeout)
            if rep.get("request_id") == rid:
                return rep
            # out-of-order reply: stash it
            self._pending[rep.get("request_id")] = rep

    def execute(self, code, cell_id="cell"):
        """REPL-order execute: parent is the client's current snapshot and
        the committed cell joins the replay ledger."""
        rep = self.request("execute", code=code, cell_id=cell_id,
                           parent_snapshot=self.snapshot)
        if rep.get("status") == "ok":
            self.snapshot = rep["snapshot"]
            self.ledger.append((cell_id, code))
        return rep

    def execute_at(self, code, cell_id, parent):
        """Document-order execute against an explicit parent snapshot.
        Not ledgered: document mode recovers by prefix revalidation."""
        rep = self.request("execute", code=code, cell_id=cell_id,
                           parent_snapshot=parent)
        if rep.get("status") == "ok":
            self.snapshot = rep["snapshot"]
        return rep

    def restart_fresh(self):
        """Fresh worker with no replay (document mode rebuilds on demand)."""
        self.kill()
        self.ledger = []
        self.start()
