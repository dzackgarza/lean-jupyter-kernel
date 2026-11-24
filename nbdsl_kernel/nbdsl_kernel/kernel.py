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
        self._published: set[tuple[str, str, str]] = set()
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
            assert rep.snapshot is not None
            self.base_snapshot = rep.snapshot
        else:
            self._init_error = f"init cell failed: {rep.first_error()}"

    def _ensure_worker(self) -> None:
        if not self._started:
            self._stream(
                "stdout", f"Starting Lean worker ({self.worker.project_root})…\n"
            )
            self.worker.start()
            # From this point the worker owns a real live session. Failure
            # during initialization does not authorize implicit force/recovery.
            self._started = True
            try:
                self._run_init_cell()
            except (WireProtocolError, WorkerDied, WorkerInterrupted, TimeoutError) as e:
                self._init_error = str(e)
                raise
        else:
            self.worker.require_session()

    def _explicit_parent(
        self, cell_id: str, silent: bool
    ) -> tuple[JupyterReply | None, int]:
        """Read already committed document snapshots; never execute predecessors."""
        parent = self.base_snapshot
        for cid in self.doc.doc_order:
            if cid == cell_id:
                return None, parent
            src = self.doc.doc_sources.get(cid, "")
            if not src.strip():
                continue
            st = self.doc.cell_state.get(cid)
            if st is None or st.source != src or st.parent != parent:
                return self._error_reply(
                    "SnapshotUnavailable",
                    "unavailable/snapshot_unavailable: execute the required predecessor explicitly",
                    silent,
                ), parent
            parent = st.snapshot
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
            return self._execute_once(code, silent, cell_id, cell_meta)
        except KeyboardInterrupt:
            return self._error_reply("Interrupted", "execution interrupted; state not established", silent)
        except WireProtocolError as e:
            return self._error_reply("WireProtocolError", str(e), silent)
        except WorkerInterrupted as e:
            return self._error_reply("Interrupted", str(e), silent)
        except WorkerDied as e:
            return self._error_reply("WorkerDied", str(e), silent)
        finally:
            self._silent = False

    def _execute_once(
        self, code: str, silent: bool, cell_id: str | None,
        cell_meta: dict[str, object] | None = None,
    ) -> JupyterReply:
        self._ensure_worker()
        if self._init_error:
            return self._error_reply("InitCellError", self._init_error, silent)
        selected = (cell_meta or {}).get("parent_snapshot")
        selected_nonce = (cell_meta or {}).get("worker_nonce")
        if selected is not None:
            if (not isinstance(selected, str) or not selected.isascii() or
                    not selected.isdecimal() or selected_nonce != self.worker.worker_nonce):
                return self._error_reply("SnapshotUnavailable", "unavailable/snapshot_unavailable", silent)
            parent = int(selected)
            rep = self.worker.execute_at(code, cell_id or "cell", parent)
            if rep.status == "ok" and cell_id:
                assert rep.snapshot is not None
                self.doc.cell_state[cell_id] = CellState(
                    source=code, snapshot=rep.snapshot, parent=parent)
                self.doc.broadcast_status(self)
        elif cell_id and cell_id in self.doc.doc_sources:
            self.doc.doc_sources[cell_id] = code
            err, parent = self._explicit_parent(cell_id, silent)
            if err is not None:
                return err
            rep = self.worker.execute_at(code, cell_id, parent)
            if rep.status == "ok":
                assert rep.snapshot is not None
                self.doc.cell_state[cell_id] = CellState(
                    source=code, snapshot=rep.snapshot, parent=parent
                )
            self.doc.broadcast_status(self)
        else:
            rep = self.worker.execute(code, cell_id=cell_id or "cell")
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
        if rep.status == "unavailable":
            return self._error_reply("WorkerUnavailable", rep.first_error(), silent)
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
        except (WireProtocolError, WorkerDied, TimeoutError):
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
        self.doc.cell_state.clear()
        self._published.clear()
        return {"status": "ok", "restart": restart}
