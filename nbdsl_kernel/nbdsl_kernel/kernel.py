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
            # The worker died — normally from an interrupt's SIGINT. Rebuild
            # the committed state by replaying the ledger: source replay is
            # the canonical record (scoped env state does not pickle).
            self._stream("stderr",
                         "Lean worker died; restarting and replaying "
                         "committed cells…\n")
            n = self.worker.restart_and_replay()
            self._stream("stderr", f"Replayed {n} cells.\n")

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
