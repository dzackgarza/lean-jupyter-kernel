"""Jupyter output rendering for worker replies.

Extracted from kernel.py so the adapter stays under the file-size ceiling.
The kernel delegates reply publishing here; the rendering logic owns the
stream/display routing for diagnostics, sorries, and outputs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .protocol import ExecuteReply
from .cas_display import render_committed

if TYPE_CHECKING:
    from .kernel import NbDslKernel


def publish_reply(kernel: NbDslKernel, rep: ExecuteReply) -> None:
    """Publish diagnostics, sorries, and outputs for an execute reply."""
    if rep.status != "ok" or rep.commit is None or rep.worker_nonce is None:
        raise ValueError("only a negotiated committed batch may be published")
    for diag in rep.diagnostics:
        if diag.severity == "error":
            continue  # errors are published once, as the error output
        # DSL diagnostics ride this channel with their source position
        # attached — for a notebook cell that position is always the
        # cell itself, so the `line:col:` prefix is pure noise. Emit the
        # message bare, whatever it says.
        text = f"{diag.message}\n"
        kernel._stream("stdout" if diag.severity == "information" else "stderr", text)
    for s in rep.sorries:
        kernel._stream(
            "stderr", f"⚠ sorry at {s.start.line}:{s.start.column}\n{s.goal}\n"
        )
    for i, out in enumerate(rep.outputs):
        identity = (rep.worker_nonce, rep.commit.output_batch_id, out.result_id)
        if identity in kernel._published:
            continue
        data = render_committed(out.data, out.metadata)
        kernel._published.add(identity)
        last = i == len(rep.outputs) - 1
        if last and rep.status == "ok":
            kernel.send_response(
                kernel.iopub_socket,
                "execute_result",
                {
                    "execution_count": kernel.execution_count,
                    "data": data,
                    "metadata": out.metadata,
                },
            )
        else:
            kernel.send_response(
                kernel.iopub_socket,
                "display_data",
                {
                    "data": data,
                    "metadata": out.metadata,
                },
            )
