"""Jupyter wrapper kernel for the nbdsl Lean worker.

A thin protocol adapter: cells go verbatim to the Lean worker, which owns
parsing, elaboration, semantic state, and proof checking; this class owns
Jupyter messaging and rendering only. Python never interprets DSL text.

Typing note: worker traffic and the ipykernel comm payloads are modeled in
protocol.py — untyped dependency data is ingested to pydantic at the
boundary. What remains untyped-by-nature: the Jupyter reply dicts returned
TO ipykernel (its API), and the __init__ **kwargs relay to traitlets.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from importlib.metadata import version
from typing import Any

from ipykernel.kernelbase import Kernel

from . import handlers
from .document import DocumentSession
from .protocol import (
    CellState,
    IsCompleteOk,
)
from .rendering import publish_reply
from .worker import WireProtocolError, WorkerClient, WorkerDied, WorkerInterrupted

JupyterReply = dict[str, object]


class NbDslKernel(Kernel):
    implementation = "nbdsl"
    implementation_version = version("nbdsl-kernel")
    banner = "NbDsl — a Lean 4 elaborated DSL"

    @property
    def language_info(self) -> dict[str, object]:
        """The session's language identity, from the kernelspec env.

        A DSL project speaks its own surface: the generic adapter defaults to
        Lean 4 (text/x-lean4), while a CasDsl kernelspec is installed with
        ``--mimetype text/x-casdsl --language-name casdsl`` so JupyterLab's
        editor routes cells to the registered CasDsl highlighter.
        """
        return {
            "name": os.environ.get("NBDSL_LANGUAGE_NAME", "lean4"),
            "mimetype": os.environ.get("NBDSL_MIMETYPE", "text/x-lean4"),
            "file_extension": os.environ.get("NBDSL_LANGUAGE_EXT", ".lean"),
        }

    @language_info.setter
    def language_info(self, value: dict[str, object]) -> None:
        # Kernel.language_info is declared writeable (kernelbase.py); the
        # kernelspec env is the source of truth here, so writes are accepted
        # and discarded.
        pass

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        project = os.environ.get("NBDSL_PROJECT")
        if not project:
            raise RuntimeError(
                "NBDSL_PROJECT is not set; install the kernelspec with "
                "`python -m nbdsl_kernel.install --project <lean project root>`"
            )
        self.worker = WorkerClient(
            project,
            prelude=os.environ.get("NBDSL_PRELUDE", "NbDsl.Notebook"),
            on_stream=self._stream,
        )
        self._started = False
        self._silent = False
        # Session defaults a prelude can't set (set_option doesn't cross
        # module import): one cell of commands run right after worker start,
        # from the kernelspec (install.py --init-cell).
        self.init_cell = os.environ.get("NBDSL_INIT", "")
        self.base_snapshot = 0
        self._init_error: str | None = None
        # Session cache (REPL-mode restarts skip replay). Not in sandbox
        # mode: the sandboxed worker cannot write outside its private tmpfs.
        if os.environ.get("NBDSL_SANDBOX") != "1":
            self.worker.cache_dir = tempfile.mkdtemp(prefix="nbdsl-cache-")
        # Document mode: the jupyterlab_nbdsl extension streams cell order and
        # sources over the "nbdsl_document" comm. Without it (jupyter console)
        # execution keeps REPL semantics.
        self.doc = DocumentSession()
        for msg_type in ("comm_open", "comm_msg", "comm_close"):
            self.shell_handlers[msg_type] = getattr(self, msg_type)

    # -- document comm -----------------------------------------------------

    async def comm_open(self, stream: object, ident: object, parent: object) -> None:
        await self.doc.comm_open(self, parent)

    async def comm_msg(self, stream: object, ident: object, parent: object) -> None:
        await self.doc.comm_msg(self, parent)

    async def comm_close(self, stream: object, ident: object, parent: object) -> None:
        await self.doc.comm_close(self, parent)

    # -- plumbing ----------------------------------------------------------

    def _stream(self, name: str, text: str) -> None:
        # self._silent exists for exactly this method: it gates output from
        # ASYNC contexts (worker stdout/stderr pump threads, prefix re-run
        # notes) that have no `silent` parameter in scope. Synchronous reply
        # paths thread `silent` explicitly instead of mutating the flag.
        if not self._silent:
            self.send_response(
                self.iopub_socket, "stream", {"name": name, "text": text}
            )

    def _run_init_cell(self) -> None:
        """The kernelspec's init cell becomes the session's base snapshot.
        A failing init cell is a broken kernelspec: fail every execute loudly
        rather than silently running without the configured defaults."""
        self.base_snapshot = 0
        self._init_error = None
        if not self.init_cell.strip():
            return
        rep = self.worker.execute(self.init_cell, cell_id="<init>")
        if rep.status == "ok":
            self.base_snapshot = rep.snapshot
        else:
            self._init_error = f"init cell failed: {rep.first_error()}"

    def _ensure_worker(self) -> None:
        if not self._started:
            self._stream(
                "stdout", f"Starting Lean worker ({self.worker.project_root})…\n"
            )
            self.worker.start()
            try:
                self._run_init_cell()
            except (WireProtocolError, WorkerDied, WorkerInterrupted, TimeoutError):
                # Bootstrap owns a live worker before `_started` flips. Make
                # a failed query-first bootstrap retryable without leaving
                # that process in WorkerClient's ownership slots.
                self.worker.kill()
                raise
            self._started = True
        elif not self.worker.running():
            # The worker died — normally from an interrupt escalation.
            if self.doc.doc_sources:
                # Document mode: snapshots are gone, so drop the cell states;
                # prefix revalidation rebuilds exactly what the next run needs.
                self._stream(
                    "stderr",
                    "Lean worker died; restarting (cells will re-run on demand)…\n",
                )
                self.worker.restart_fresh()
                self.doc.cell_state.clear()
                self._run_init_cell()
            else:
                # REPL mode: session cache when valid, else source replay
                # (the canonical record).
                self._stream("stderr", "Lean worker died; restarting…\n")
                n = self.worker.restart_and_replay()
                if n == -1:
                    self._stream("stderr", "Restored session from cache.\n")
                else:
                    self._stream("stderr", f"Replayed {n} cells.\n")

    def _ensure_prefix(
        self, cell_id: str, silent: bool
    ) -> tuple[JupyterReply | None, int]:
        """Re-establish the invariant: the snapshot for each cell equals the
        state of elaborating the visible notebook prefix through that cell.
        Returns (error_reply | None, parent_snapshot_for_cell_id)."""
        parent = self.base_snapshot  # prelude, plus the init cell if any
        for cid in self.doc.doc_order:
            if cid == cell_id:
                return None, parent
            src = self.doc.doc_sources.get(cid, "")
            if not src.strip():
                continue
            st = self.doc.cell_state.get(cid)
            if st is not None and st.source == src and st.parent == parent:
                parent = st.snapshot
                continue
            pos = self.doc.doc_order.index(cid) + 1
            self._stream("stdout", f"↻ re-running upstream cell {pos}…\n")
            rep = self.worker.execute_at(src, cid, parent)
            if rep.status != "ok":
                return self._error_reply(
                    "UpstreamError",
                    f"upstream cell {pos} failed: {rep.first_error()}",
                    silent,
                ), parent
            self.doc.cell_state[cid] = CellState(
                source=src, snapshot=rep.snapshot, parent=parent
            )
            parent = rep.snapshot
        # cell not in the document (e.g. brand-new cell the extension hasn't
        # reported yet): fall through with the last prefix state
        return None, parent

    # -- Jupyter entry points ---------------------------------------------

    async def do_execute(
        self,
        code: str,
        silent: bool,
        store_history: bool = True,
        user_expressions: dict[str, object] | None = None,
        allow_stdin: bool = False,
        *,
        cell_meta: dict[str, object] | None = None,
        cell_id: str | None = None,
    ) -> JupyterReply:
        self._silent = silent
        try:
            return self._execute_once(code, silent, cell_id)
        except KeyboardInterrupt:
            # Jupyter interrupts SIGINT the whole process group; the worker is
            # (being) killed. Kill it outright so no stale elaboration lingers;
            # the next execute restarts and replays the committed prefix.
            self.worker.kill()
            return self._error_reply("Interrupted", "execution interrupted", silent)
        except WireProtocolError as e:
            # Loud-init-failure pattern: the kernel starts and answers
            # kernel_info, and every execute reports this instead.
            return self._error_reply("WireProtocolError", str(e), silent)
        except WorkerInterrupted:
            return self._error_reply(
                "Interrupted",
                "execution interrupted; worker killed after "
                "the cooperative-cancel window",
                silent,
            )
        except WorkerDied as e:
            # A request was sent but no reply arrived. The worker may have
            # committed external effects before dying, so this cell is never
            # retry-safe. Reap it now; a later user request restarts and
            # replays only the previously acknowledged ledger.
            self.worker.kill()
            return self._error_reply("WorkerDied", str(e), silent)
        finally:
            self._silent = False

    def _execute_once(
        self, code: str, silent: bool, cell_id: str | None
    ) -> JupyterReply:
        self._ensure_worker()
        if self._init_error:
            return self._error_reply("InitCellError", self._init_error, silent)
        if cell_id and cell_id in self.doc.doc_sources:
            # Document mode: make the prefix invariant true, then run this
            # cell against its prefix snapshot. The request's code is the
            # authoritative source for the cell itself.
            self.doc.doc_sources[cell_id] = code
            err, parent = self._ensure_prefix(cell_id, silent)
            if err is not None:
                return err
            rep = self.worker.execute_at(code, cell_id, parent)
            if rep.status == "ok":
                self.doc.cell_state[cell_id] = CellState(
                    source=code, snapshot=rep.snapshot, parent=parent
                )
            self.doc.broadcast_status(self)
        else:
            rep = self.worker.execute(code, cell_id=cell_id or "cell")
            if rep.status == "ok":
                self.worker.save_session()
        if not silent and rep.status == "ok":
            publish_reply(self, rep)
        if rep.status == "ok":
            return {
                "status": "ok",
                "execution_count": self.execution_count,
                "payload": [],
                "user_expressions": {},
            }
        if rep.status == "cancelled":
            return self._error_reply(
                "Interrupted", "execution cancelled; state unchanged", silent
            )
        return self._error_reply("LeanError", rep.first_error(), silent)

    def _error_reply(self, ename: str, evalue: str, silent: bool) -> JupyterReply:
        if not silent:
            self.send_response(
                self.iopub_socket,
                "error",
                {
                    "ename": ename,
                    "evalue": evalue,
                    "traceback": [evalue],
                },
            )
        return {
            "status": "error",
            "ename": ename,
            "evalue": evalue,
            "traceback": [evalue],
            "execution_count": self.execution_count,
        }

    async def do_is_complete(self, code: str) -> JupyterReply:
        # Deciding completeness requires Lean's parser — never guessed in
        # Python. is_complete_reply has no error status in the Jupyter spec,
        # so "unknown" is the spec's honest answer for every cannot-determine
        # state (worker not started, worker dead) — a ceiling, not a fallback.
        if not self._started:
            return {"status": "unknown"}
        try:
            rep = self.worker.is_complete(code)
        except (WorkerDied, TimeoutError):
            return {"status": "unknown"}
        if not isinstance(rep, IsCompleteOk):
            return {"status": "unknown"}
        out: JupyterReply = {"status": rep.result}
        if rep.result == "incomplete":
            out["indent"] = "  "
        return out

    async def do_complete(self, code: str, cursor_pos: int) -> JupyterReply:
        return await handlers.do_complete(self, code, cursor_pos)

    async def do_inspect(
        self,
        code: str,
        cursor_pos: int,
        detail_level: int = 0,
        omit_sections: tuple[object, ...] = (),
    ) -> JupyterReply:
        return await handlers.do_inspect(
            self, code, cursor_pos, detail_level, omit_sections
        )

    async def do_shutdown(self, restart: bool) -> JupyterReply:
        if self._started:
            self.worker.shutdown()
            self._started = False
        if self.worker.cache_dir:
            shutil.rmtree(self.worker.cache_dir, ignore_errors=True)
        return {"status": "ok", "restart": restart}
