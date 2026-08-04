"""Document-mode comm handling for the nbdsl kernel.

Extracted from kernel.py so the adapter stays under the file-size ceiling.
The kernel delegates comm routing and cell-status broadcasting here; this
module owns the document-order/source bookkeeping and the fresh/stale
status broadcasts that the jupyterlab_nbdsl extension consumes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import ValidationError

from .protocol import CellState, CommParent, DocumentMessage

if TYPE_CHECKING:
    from .kernel import NbDslKernel


class DocumentSession:
    """Tracks the visible notebook (cell order + sources) and broadcasts
    fresh/stale status to the frontend over the ``nbdsl_document`` comm."""

    def __init__(self) -> None:
        self._doc_comms: set[str] = set()
        self.doc_order: list[str] = []
        self.doc_sources: dict[str, str] = {}
        self.cell_state: dict[str, CellState] = {}

    def is_document_mode(self) -> bool:
        return bool(self._doc_comms)

    async def comm_open(self, kernel: NbDslKernel, parent: object) -> None:
        msg = CommParent.model_validate(parent)
        if msg.content.target_name == "nbdsl_document":
            self._doc_comms.add(msg.content.comm_id)

    async def comm_msg(self, kernel: NbDslKernel, parent: object) -> None:
        msg = CommParent.model_validate(parent)
        if msg.content.comm_id not in self._doc_comms:
            return
        try:
            doc = DocumentMessage.model_validate(msg.content.data)
        except ValidationError:
            # Status broadcasts echo on this comm and any frontend code may
            # open the target; non-document traffic is ignored, not fatal.
            return
        self.doc_order = [c.id for c in doc.cells]
        self.doc_sources = {c.id: c.source for c in doc.cells}
        self.broadcast_status(kernel)

    async def comm_close(self, kernel: NbDslKernel, parent: object) -> None:
        self._doc_comms.discard(CommParent.model_validate(parent).content.comm_id)

    def broadcast_status(self, kernel: NbDslKernel) -> None:
        """Tell the frontend which cells are fresh vs stale (previously run,
        now invalidated by an upstream edit). Unrun cells are in neither."""
        if not self._doc_comms or not self.doc_order or kernel.session is None:
            return
        fresh: list[str] = []
        stale: list[str] = []
        parent = kernel.base_snapshot
        broken = False
        for cid in self.doc_order:
            src = self.doc_sources.get(cid, "")
            if not src.strip():
                continue
            st = self.cell_state.get(cid)
            if (
                not broken
                and st is not None
                and st.source == src
                and st.parent == parent
            ):
                fresh.append(cid)
                parent = st.snapshot
            else:
                broken = True
                if st is not None:
                    stale.append(cid)
        data = {"type": "status", "fresh": fresh, "stale": stale}
        for comm_id in self._doc_comms:
            kernel.session.send(
                kernel.iopub_socket, "comm_msg", {"comm_id": comm_id, "data": data}
            )
