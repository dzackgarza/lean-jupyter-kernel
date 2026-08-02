"""Typed model of the worker wire protocol.

Pydantic is the type boundary: raw frames (JSON) become these models inside
`WorkerClient`, and nothing above the transport handles untyped dicts. A
malformed worker reply raises ValidationError — a protocol violation is a
crash, not a soft default. Extra fields are ignored (the worker may grow
fields; old clients keep working).

The wire tests (roundtrip.py / test_e2e.py) deliberately do NOT use these
models: they read raw JSON as an independent oracle for the protocol itself.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

PositivePid = Annotated[int, Field(gt=0)]

# Must match Worker.Protocol.wireProtocol / release.toml compat.wire_protocol.
WIRE_PROTOCOL = 1


class _Frame(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    request_id: str | None = None


class Position(BaseModel):
    line: int
    column: int  # Unicode code points, end to end


class Diagnostic(BaseModel):
    severity: Literal["information", "warning", "error"]
    message: str
    start: Position
    end: Position | None = None


class SorryInfo(BaseModel):
    start: Position
    end: Position | None = None
    goal: str


class OutputBundle(BaseModel):
    """A MIME bundle; payload shapes are renderer-owned, not modeled here."""

    data: dict[str, object]
    metadata: dict[str, object] = Field(default_factory=dict)
    display_id: str | None = None


class ReadyFrame(_Frame):
    op: Literal["ready"]
    protocol: int
    lean: str
    #: Host PID of the worker. Under Bubblewrap this is rewritten by the
    #: client from the namespace-local ready value to the host-visible PID.
    pid: PositivePid
    snapshot: int
    release: str | None = None


class ExecuteReply(_Frame):
    status: Literal["ok", "error", "cancelled"]
    snapshot: int
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    sorries: list[SorryInfo] = Field(default_factory=list)
    outputs: list[OutputBundle] = Field(default_factory=list)

    def first_error(self, fallback: str = "execution failed") -> str:
        return next((d.message for d in self.diagnostics
                     if d.severity == "error"), fallback)


class WorkerError(_Frame):
    """The worker's generic failure reply for non-execute ops."""

    status: Literal["error"]
    message: str


class CompleteOk(_Frame):
    status: Literal["ok"]
    matches: list[str]
    cursor_start: int
    cursor_end: int


class InspectOk(_Frame):
    status: Literal["ok"]
    found: bool
    hover: str | None = None
    name: str | None = None
    type_: str | None = Field(default=None, alias="type")
    doc: str | None = None


class IsCompleteOk(_Frame):
    status: Literal["ok"]
    result: Literal["complete", "incomplete", "invalid"]


class SaveSessionOk(_Frame):
    status: Literal["ok"]
    saved: bool
    reason: str | None = None


class LoadSessionOk(_Frame):
    status: Literal["ok"]
    snapshot: int


COMPLETE_REPLY: TypeAdapter[CompleteOk | WorkerError] = TypeAdapter(
    Annotated[CompleteOk | WorkerError, Field(discriminator="status")])
INSPECT_REPLY: TypeAdapter[InspectOk | WorkerError] = TypeAdapter(
    Annotated[InspectOk | WorkerError, Field(discriminator="status")])
IS_COMPLETE_REPLY: TypeAdapter[IsCompleteOk | WorkerError] = TypeAdapter(
    Annotated[IsCompleteOk | WorkerError, Field(discriminator="status")])
SAVE_SESSION_REPLY: TypeAdapter[SaveSessionOk | WorkerError] = TypeAdapter(
    Annotated[SaveSessionOk | WorkerError, Field(discriminator="status")])
LOAD_SESSION_REPLY: TypeAdapter[LoadSessionOk | WorkerError] = TypeAdapter(
    Annotated[LoadSessionOk | WorkerError, Field(discriminator="status")])


# -- ipykernel ingestion boundary -------------------------------------------
# ipykernel hands handlers untyped message dicts; these models re-type that
# dependency at the door (POLICY.NO_UNTYPED_IMPORT_LEAK). Only the fields the
# kernel reads are modeled; the rest is ignored.

class CommContent(BaseModel):
    comm_id: str
    target_name: str | None = None
    data: object = None


class CommParent(BaseModel):
    content: CommContent


# -- kernel-side document model (frontend comm boundary) --------------------

class DocCell(BaseModel):
    id: str
    source: str


class DocumentMessage(BaseModel):
    type: Literal["document"]
    cells: list[DocCell]


class CellState(BaseModel):
    """Committed execution state of one notebook cell."""

    source: str
    snapshot: int
    parent: int
