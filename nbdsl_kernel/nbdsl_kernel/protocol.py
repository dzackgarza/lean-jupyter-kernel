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

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

PositivePid = Annotated[int, Field(gt=0)]

# Must match Worker.Protocol.wireProtocol / release.toml compat.wire_protocol.
WIRE_PROTOCOL = 2
SESSION_POLICY = "cas_no_replay"
NOTEBOOK_FEATURES = frozenset({
    "cas-session/2", "explicit-parent/2", "atomic-cell/2",
    "inspect-environment/2", "complete-environment/2", "cancel-by-request/2",
    "no-replay/2", "no-session-cache/2",
})


class FrozenProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Annotated[str, Field(min_length=1)]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class CommitReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transaction_id: Annotated[str, Field(min_length=1)]
    output_batch_id: Annotated[str, Field(min_length=1)]
    profile_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    result_refs: list[str]


def snapshot_serial(value: object) -> int:
    """The wire has decimal strings, never JSON numbers or coerced booleans."""
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        raise ValueError("snapshot must be a decimal string")
    if len(value) > 1 and value.startswith("0"):
        raise ValueError("snapshot must use its canonical decimal serial")
    return int(value)


class _Frame(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    request_id: str | None = None
    worker_nonce: str | None = None


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

    result_id: Annotated[str, Field(min_length=1)]
    data: dict[str, object] = Field(alias="mime")
    metadata: dict[str, object] = Field(default_factory=dict)
    display_id: str | None = None

    @field_validator("data")
    @classmethod
    def usable_text(cls, data: dict[str, object]) -> dict[str, object]:
        if not isinstance(data.get("text/plain"), str) or not data["text/plain"]:
            raise ValueError("a committed result needs usable text/plain")
        return data


class ReadyFrame(_Frame):
    op: Literal["ready"]
    protocol: int
    lean: str
    #: Host PID of the worker. Under Bubblewrap this is rewritten by the
    #: client from the namespace-local ready value to the host-visible PID.
    pid: PositivePid
    snapshot: int
    release: str | None = None
    realization_profile: FrozenProfile | None = None
    features: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def validate_snapshot(cls, value: object) -> object:
        # Keep a parseable legacy ready frame solely to reject it at the version gate.
        if isinstance(value, dict) and value.get("protocol") == WIRE_PROTOCOL:
            return {**value, "snapshot": snapshot_serial(value.get("snapshot"))}
        return value


class ExecuteReply(_Frame):
    status: Literal["ok", "error", "cancelled"]
    snapshot: int
    parent_snapshot: int
    commit: CommitReceipt | None = None
    reason: str | None = None
    stratum: str | None = None
    message: str | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    sorries: list[SorryInfo] = Field(default_factory=list)
    outputs: list[OutputBundle] = Field(default_factory=list)

    @field_validator("snapshot", "parent_snapshot", mode="before")
    @classmethod
    def validate_serial(cls, value: object) -> int:
        return snapshot_serial(value)

    @model_validator(mode="after")
    def publication(self) -> ExecuteReply:
        if self.status == "ok":
            if self.commit is None or self.snapshot == self.parent_snapshot:
                raise ValueError("success requires a new committed snapshot and receipt")
            if len({out.result_id for out in self.outputs}) != len(self.outputs):
                raise ValueError("duplicate committed result identity")
        elif self.commit is not None or self.outputs or self.snapshot != self.parent_snapshot:
            raise ValueError("failed/cancelled execution cannot publish a delta")
        return self

    def first_error(self, fallback: str = "execution failed") -> str:
        detail = next((d.message for d in self.diagnostics
                       if d.severity == "error"), self.message or fallback)
        return f"{self.stratum or 'unavailable'}/{self.reason}: {detail}" if self.reason else detail


class WorkerError(_Frame):
    """The worker's generic failure reply for non-execute ops."""

    status: Literal["error", "unavailable"]
    message: str
    reason: str | None = None


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
    result: Literal["complete", "incomplete", "invalid", "unknown"]


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
