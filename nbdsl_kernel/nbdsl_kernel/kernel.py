"""Jupyter wrapper kernel for the nbdsl Lean worker.

A thin protocol adapter: cells go verbatim to the Lean worker, which owns
parsing, elaboration, semantic state, and proof checking; this class owns
Jupyter messaging and rendering only. Python never interprets DSL text.
"""

import os

from ipykernel.kernelbase import Kernel

from .worker import WorkerClient, WorkerDied


class NbDslKernel(Kernel):
    implementation = "nbdsl"
    implementation_version = "0.1"
    banner = "NbDsl — a Lean 4 elaborated DSL"
    language_info = {
        "name": "lean4",
        "mimetype": "text/x-lean4",
        "file_extension": ".lean",
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        project = os.environ.get("NBDSL_PROJECT")
        if not project:
            raise RuntimeError(
                "NBDSL_PROJECT is not set; install the kernelspec with "
                "`python -m nbdsl_kernel.install --project <lean project root>`")
        self.worker = WorkerClient(project, on_stream=self._stream)
        self._started = False
        self._silent = False
        # Document mode: the jupyterlab_nbdsl extension streams cell order and
        # sources over the "nbdsl_document" comm. Without it (jupyter console)
        # execution keeps REPL semantics.
        self._doc_comms = set()
        self.doc_order = []          # cell ids, visible order (code cells)
        self.doc_sources = {}        # cell id -> source
        self.cell_state = {}         # cell id -> {source, snapshot, parent}
        for msg_type in ("comm_open", "comm_msg", "comm_close"):
            self.shell_handlers[msg_type] = getattr(self, msg_type)

    # -- document comm -----------------------------------------------------

    async def comm_open(self, stream, ident, parent):
        content = parent["content"]
        if content.get("target_name") == "nbdsl_document":
            self._doc_comms.add(content.get("comm_id"))

    async def comm_msg(self, stream, ident, parent):
        content = parent["content"]
        if content.get("comm_id") not in self._doc_comms:
            return
        data = content.get("data", {})
        if data.get("type") == "document":
            cells = data.get("cells", [])
            self.doc_order = [c["id"] for c in cells]
            self.doc_sources = {c["id"]: c["source"] for c in cells}

    async def comm_close(self, stream, ident, parent):
        self._doc_comms.discard(parent["content"].get("comm_id"))

    # -- plumbing ----------------------------------------------------------

    def _stream(self, name, text):
        if not self._silent:
            self.send_response(self.iopub_socket, "stream",
                               {"name": name, "text": text})

    def _ensure_worker(self):
        if not self._started:
            self._stream("stdout",
                         f"Starting Lean worker ({self.worker.project_root})…\n")
            self.worker.start()
            self._started = True
        elif self.worker.proc is None or self.worker.proc.poll() is not None:
            # The worker died — normally from an interrupt escalation.
            if self.doc_sources:
                # Document mode: snapshots are gone, so drop the cell states;
                # prefix revalidation rebuilds exactly what the next run needs.
                self._stream("stderr", "Lean worker died; restarting (cells "
                                       "will re-run on demand)…\n")
                self.worker.restart_fresh()
                self.cell_state.clear()
            else:
                # REPL mode: source replay of the ledger is the canonical
                # record (scoped env state does not pickle).
                self._stream("stderr", "Lean worker died; restarting and "
                                       "replaying committed cells…\n")
                n = self.worker.restart_and_replay()
                self._stream("stderr", f"Replayed {n} cells.\n")

    def _ensure_prefix(self, cell_id):
        """Re-establish the invariant: the snapshot for each cell equals the
        state of elaborating the visible notebook prefix through that cell.
        Returns (error_reply | None, parent_snapshot_for_cell_id)."""
        parent = 0  # the prelude snapshot
        for cid in self.doc_order:
            if cid == cell_id:
                return None, parent
            src = self.doc_sources.get(cid, "")
            if not src.strip():
                continue
            st = self.cell_state.get(cid)
            if st and st["source"] == src and st["parent"] == parent:
                parent = st["snapshot"]
                continue
            pos = self.doc_order.index(cid) + 1
            self._stream("stdout", f"↻ re-running upstream cell {pos}…\n")
            rep = self.worker.execute_at(src, cid, parent)
            if rep.get("status") != "ok":
                first = next((d for d in rep.get("diagnostics", [])
                              if d["severity"] == "error"), {"message": "failed"})
                return self._error_reply(
                    "UpstreamError",
                    f"upstream cell {pos} failed: {first['message']}"), parent
            self.cell_state[cid] = {"source": src,
                                    "snapshot": rep["snapshot"], "parent": parent}
            parent = rep["snapshot"]
        # cell not in the document (e.g. brand-new cell the extension hasn't
        # reported yet): fall through with the last prefix state
        return None, parent

    def _publish_reply(self, rep):
        for diag in rep.get("diagnostics", []):
            sev = diag["severity"]
            if sev == "error":
                continue  # errors are published once, as the error output
            pos = diag["start"]
            text = f"{pos['line']}:{pos['column']}: {diag['message']}\n"
            self._stream("stdout" if sev == "information" else "stderr", text)
        for s in rep.get("sorries", []):
            pos = s["start"]
            self._stream(
                "stderr",
                f"⚠ sorry at {pos['line']}:{pos['column']}\n{s['goal']}\n")
        outputs = rep.get("outputs", [])
        for i, out in enumerate(outputs):
            data = dict(out["data"])
            data.setdefault("text/plain", "<nbdsl output>")
            last = i == len(outputs) - 1
            if last and rep.get("status") == "ok":
                self.send_response(self.iopub_socket, "execute_result", {
                    "execution_count": self.execution_count,
                    "data": data,
                    "metadata": out.get("metadata") or {},
                })
            else:
                self.send_response(self.iopub_socket, "display_data", {
                    "data": data,
                    "metadata": out.get("metadata") or {},
                })

    # -- Jupyter entry points ---------------------------------------------

    def do_execute(self, code, silent, store_history=True,
                   user_expressions=None, allow_stdin=False, *,
                   cell_meta=None, cell_id=None):
        self._silent = silent
        try:
            self._ensure_worker()
            if cell_id and cell_id in self.doc_sources:
                # Document mode: make the prefix invariant true, then run this
                # cell against its prefix snapshot. The request's code is the
                # authoritative source for the cell itself.
                self.doc_sources[cell_id] = code
                err, parent = self._ensure_prefix(cell_id)
                if err is not None:
                    return err
                rep = self.worker.execute_at(code, cell_id, parent)
                if rep.get("status") == "ok":
                    self.cell_state[cell_id] = {
                        "source": code, "snapshot": rep["snapshot"],
                        "parent": parent}
            else:
                rep = self.worker.execute(code, cell_id=cell_id or "cell")
            if not silent:
                self._publish_reply(rep)
            if rep.get("status") == "ok":
                return {"status": "ok", "execution_count": self.execution_count,
                        "payload": [], "user_expressions": {}}
            if rep.get("status") == "cancelled":
                return self._error_reply("Interrupted",
                                         "execution cancelled; state unchanged")
            first = next((d for d in rep.get("diagnostics", [])
                          if d["severity"] == "error"),
                         {"message": "execution failed"})
            return self._error_reply("LeanError", first["message"])
        except KeyboardInterrupt:
            # Jupyter interrupts SIGINT the whole process group; the worker is
            # (being) killed. Kill it outright so no stale elaboration lingers;
            # the next execute restarts and replays the committed prefix.
            self.worker.kill()
            return self._error_reply("Interrupted", "execution interrupted")
        except WorkerDied as e:
            return self._error_reply("WorkerDied", str(e))
        finally:
            self._silent = False

    def _error_reply(self, ename, evalue):
        if not self._silent:
            self.send_response(self.iopub_socket, "error", {
                "ename": ename, "evalue": evalue,
                "traceback": [evalue],
            })
        return {"status": "error", "ename": ename, "evalue": evalue,
                "traceback": [evalue], "execution_count": self.execution_count}

    def do_is_complete(self, code):
        # Deciding completeness requires Lean's parser — never guessed in
        # Python. Before the worker is up, the honest answer is unknown.
        if not self._started:
            return {"status": "unknown"}
        try:
            rep = self.worker.request("is_complete", code=code, timeout=30)
        except (WorkerDied, TimeoutError):
            return {"status": "unknown"}
        if rep.get("status") != "ok":
            return {"status": "unknown"}
        result = rep.get("result", "unknown")
        out = {"status": result}
        if result == "incomplete":
            out["indent"] = "  "
        return out

    def do_complete(self, code, cursor_pos):
        # cursor_pos is Unicode code points — the worker's convention too.
        empty = {"status": "ok", "matches": [], "cursor_start": cursor_pos,
                 "cursor_end": cursor_pos, "metadata": {}}
        if not self._started:
            return empty
        try:
            rep = self.worker.request("complete", code=code,
                                      cursor=cursor_pos, timeout=30)
        except (WorkerDied, TimeoutError):
            return empty
        if rep.get("status") != "ok":
            return empty
        return {"status": "ok", "matches": rep.get("matches", []),
                "cursor_start": rep.get("cursor_start", cursor_pos),
                "cursor_end": rep.get("cursor_end", cursor_pos),
                "metadata": {}}

    def do_inspect(self, code, cursor_pos, detail_level=0, omit_sections=()):
        missing = {"status": "ok", "found": False, "data": {}, "metadata": {}}
        if not self._started:
            return missing
        try:
            rep = self.worker.request("inspect", code=code,
                                      cursor=cursor_pos, timeout=30)
        except (WorkerDied, TimeoutError):
            return missing
        if rep.get("status") != "ok" or not rep.get("found"):
            return missing
        text = f"{rep['name']} : {rep['type']}"
        if rep.get("doc"):
            text += f"\n\n{rep['doc']}"
        return {"status": "ok", "found": True,
                "data": {"text/plain": text}, "metadata": {}}

    def do_shutdown(self, restart):
        if self._started:
            self.worker.shutdown()
            self._started = False
        return {"status": "ok", "restart": restart}
