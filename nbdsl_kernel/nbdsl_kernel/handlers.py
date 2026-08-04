"""Completion and inspection handlers for the nbdsl kernel.

Extracted from kernel.py so the adapter stays under the file-size ceiling.
Each handler delegates to the worker and maps the reply to the Jupyter
reply shape; failures surface loudly (a dead worker never masquerades as
"no matches" or "not found").
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .protocol import CompleteOk, InspectOk
from .worker import WireProtocolError, WorkerDied

if TYPE_CHECKING:
    from .kernel import JupyterReply, NbDslKernel


async def do_complete(kernel: NbDslKernel, code: str, cursor_pos: int) -> JupyterReply:
    # cursor_pos is Unicode code points — the worker's convention too.
    empty: JupyterReply = {
        "status": "ok",
        "matches": [],
        "cursor_start": cursor_pos,
        "cursor_end": cursor_pos,
        "metadata": {},
    }
    try:
        # Query requests are a valid first interaction. Bootstrap the
        # same prelude and init-cell state as execute_request.
        kernel._ensure_worker()
        if kernel._init_error:
            return {
                **empty,
                "status": "error",
                "ename": "InitCellError",
                "evalue": kernel._init_error,
                "traceback": [kernel._init_error],
            }
        rep = kernel.worker.complete(code, cursor_pos)
    except (WireProtocolError, WorkerDied, TimeoutError) as e:
        # Fail loudly: a dead worker must not masquerade as "no matches".
        return {
            **empty,
            "status": "error",
            "ename": type(e).__name__,
            "evalue": str(e),
            "traceback": [str(e)],
        }
    if not isinstance(rep, CompleteOk):
        return {
            **empty,
            "status": "error",
            "ename": "WorkerError",
            "evalue": rep.message,
            "traceback": [],
        }
    return {
        "status": "ok",
        "matches": rep.matches,
        "cursor_start": rep.cursor_start,
        "cursor_end": rep.cursor_end,
        "metadata": {},
    }


async def do_inspect(
    kernel: NbDslKernel,
    code: str,
    cursor_pos: int,
    detail_level: int = 0,
    omit_sections: tuple[object, ...] = (),
) -> JupyterReply:
    missing: JupyterReply = {
        "status": "ok",
        "found": False,
        "data": {},
        "metadata": {},
    }
    try:
        # Inspection, like completion, may bootstrap a fresh kernel.
        kernel._ensure_worker()
        if kernel._init_error:
            return {
                "status": "error",
                "ename": "InitCellError",
                "evalue": kernel._init_error,
                "traceback": [kernel._init_error],
            }
        rep = kernel.worker.inspect(code, cursor_pos)
    except (WireProtocolError, WorkerDied, TimeoutError) as e:
        # Fail loudly: a dead worker must not masquerade as "not found".
        return {
            **missing,
            "status": "error",
            "ename": type(e).__name__,
            "evalue": str(e),
            "traceback": [str(e)],
        }
    if not isinstance(rep, InspectOk):
        return {
            **missing,
            "status": "error",
            "ename": "WorkerError",
            "evalue": rep.message,
            "traceback": [],
        }
    if not rep.found:
        return missing
    if rep.hover:
        # Server-grade hover (markdown; covers locals and full terms).
        return {
            "status": "ok",
            "found": True,
            "data": {"text/plain": rep.hover, "text/markdown": rep.hover},
            "metadata": {},
        }
    text = f"{rep.name} : {rep.type_}"
    if rep.doc:
        text += f"\n\n{rep.doc}"
    return {
        "status": "ok",
        "found": True,
        "data": {"text/plain": text},
        "metadata": {},
    }
