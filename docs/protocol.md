# The worker wire protocol

Executable spec: `nbdsl_kernel/tests/roundtrip.py` (deliberately raw JSON —
an independent oracle whose frame codec must NOT be deduplicated with the
client's). Typed client model: `nbdsl_kernel/nbdsl_kernel/protocol.py`.

## Transport

- Two pipes, passed as inherited fds (`--req-fd N`, `--rep-fd M`); the
  worker reopens them via `/dev/fd/N`. stdout/stderr are ordinary user
  streams and can never corrupt control traffic.
- Frame = ASCII byte length, `\n`, then that many bytes of UTF-8 JSON.
- Requests carry `request_id`; the matching reply echoes it. Replies to
  different requests never interleave frames, but a reply may arrive after
  a client-side timeout — clients must match on `request_id` (the shipped
  client stashes strays).
- On startup the worker emits one unsolicited frame:
  `{"op":"ready","protocol":1,"lean":"4.32.0","snapshot":0,"pid":N}`
  (`release` may also appear; it is informational). The adapter refuses
  startup when `protocol` disagrees with its own `WIRE_PROTOCOL`
  (`WireProtocolError`).
- EOF on the request fd is a clean shutdown: the worker drains its queue
  and exits 0.

## Conventions

- All cursor and position **columns are Unicode code points** (Lean
  `FileMap` ↔ Jupyter `cursor_pos`); no byte/code-point conversion exists
  anywhere. Lines are 1-based, columns 0-based.
- Unknown ops answer `{"status":"unsupported","op":...}` — the
  forward-compatibility seam.
- Extra reply fields must be ignored by clients (the typed client does).

## Ops

### `execute {code, cell_id, parent_snapshot}`

Elaborates one cell (any number of commands) against the parent snapshot.

Reply: `{status, snapshot, diagnostics, sorries, outputs}` with
`status ∈ {"ok","error","cancelled"}`.

- `ok`: a new snapshot was committed; `snapshot` is its id.
- `error`: nothing committed; `snapshot` echoes the parent. Atomicity is
  per cell: a cell whose second command fails discards its first command's
  declarations too.
- `cancelled`: a `cancel` frame landed and elaboration reached a
  checkpoint; nothing committed.
- `diagnostics`: `{severity: information|warning|error, message,
  start:{line,column}, end?}` — accumulated across all commands of the
  cell.
- `sorries`: `{start, end?, goal}` collected from the cell's info trees
  (tactic and term sorries, deduplicated by position).
- `outputs`: MIME bundles emitted by the DSL through `Worker.emitOutput`:
  `{data: {mime: payload,...}, metadata, display_id?}`. Request-local; the
  sink is cleared before and drained after each cell.

### `cancel {request_id}`

Out-of-band (handled by the reader task, not queued). Sets the in-flight
execute's cancellation token if the id matches. **No reply of its own** —
the cancelled execute replies `status:"cancelled"`. Code that never reaches
an elaboration checkpoint (e.g. an interpreted `#eval` loop) cannot be
cancelled cooperatively; clients escalate by killing the worker's process
group after a grace window.

### `is_complete {code}`

Parse-only classification against the current snapshot's scopes (syntax
tables, opens): `{status:"ok", result: complete|incomplete|invalid}`.
`incomplete` = every parse error sits at end of input. Note that Lean's
grammar accepts some prefixes you might not expect (`example : True := by`
parses — the empty tactic block fails at elaboration, not parse).

### `complete {code, cursor}`

`{status:"ok", matches, cursor_start, cursor_end}`. Type-aware dot
completion first (resolve the head identifier, `whnf` its type, offer the
head constant's namespace members — `Object` unfolding included), falling
back to open-aware prefix completion over the environment. Results are
sorted, deduplicated, capped at 100.

### `inspect {code, cursor}`

`{status:"ok", found, hover?, name?, type?, doc?}`. `hover` is the
server-grade markdown (locals included) from analysis-elaborating the cell;
`name`/`type`/`doc` come from environment resolution when the identifier is
global. Analysis executes the cell's elaboration (side effects run), but
commits nothing and leaks no outputs.

### `save_session {path}` / `load_session {path}`

`save_session` → `{status:"ok", saved, reason?}` — writes the current
snapshot as generation-numbered `NbdslSessionCache<Nat>.olean` (constants +
persistent env-extension entries, i.e. DSL registries survive), plus
`module.txt` naming the active generation and `scope.json`. Refuses
(`saved:false` + reason) on open scopes, `variable` declarations, or
syntax-valued options.

`load_session` → `{status:"ok", snapshot}` or `{status:"error", message}` —
imports the cache module and pushes the rebuilt state as a new snapshot.
Any failure is a cache miss; clients fall back to replay. The cache is
toolchain-bound like any olean; the shipped client keys it by
prelude + ledger hash.

### `describe {}`

`{status:"ok", protocol, lean, snapshot, snapshot_count}`.

## Wire protocol version

`protocol` on `ready` / `describe` is the sole compatibility gate between
adapter and worker. It must match `Worker.Protocol.wireProtocol` /
`release.toml` `compat.wire_protocol` / `nbdsl_kernel.protocol.WIRE_PROTOCOL`.
A mismatch surfaces as a typed `WireProtocolError` on execute (the kernel
still answers `kernel_info`). There is no build-identity or provenance
comparison and no `nbdsl_provenance` comm.

## Client-side contracts (not wire, but load-bearing)

- The replay ledger (committed `(cell_id, code)` pairs in REPL mode) is the
  canonical recovery record; the session cache is a validated shortcut.
- Killing the worker means `os.killpg` on the worker's process group.
