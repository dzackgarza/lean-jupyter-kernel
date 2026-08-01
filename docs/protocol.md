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
  `{"op":"ready","protocol":1,"lean":"4.32.0","snapshot":0,"pid":N, …identity}`,
  where `…identity` is the build identity below.
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

`{status:"ok", protocol, lean, snapshot, snapshot_count, …identity}`.

## Build identity

`ready` and `describe` both carry the identity of the binary answering:

`{release, commit, dirty, plugin_api, wire, toolchain, mathlib}`

Everything but `commit`/`dirty` is a projection of the repository's authored
`release.toml` (`Worker.ReleaseInfo`); `commit` and `dirty` describe the git
checkout the binary was built from (`Worker.BuildCommit`, generated by the
lakefile's `buildCommit` target). `protocol` is `wire` — one owner, no
literal. The adapter carries the same object, computed by
`nbdsl_kernel/_identity.py` from the same `release.toml` — baked into the
wheel by `hatch_build.py`, and refreshed in a source tree by
`scripts/sync_build_info.py`. One implementation, so the two callers cannot
drift.

`dirty` means TRACKED modifications only (`git status --porcelain
--untracked-files=no`, the definition `git describe --dirty` uses and the one
both halves share). A package manager writing into the checkout must not make
an otherwise pristine install report dirty: `uv pip install git+…` leaves an
untracked `.ok` sentinel, which once made every uv-installed adapter dirty and
so silently disabled the clean-pair commit comparison on the documented
consumer install path.

What the adapter does with the pair:

| Disagreement | Result |
| --- | --- |
| `release`, `plugin_api`, `wire`, `toolchain` | always refuses — these are projections of the authored contract, so disagreement is a real incompatibility |
| `commit`, both trees clean | refuses (the release, CI, and consumer case) |
| `commit`, either tree dirty | runs, `agreed: "unverifiable-dirty"` |
| `mathlib` | never compared — it belongs to the plugin's project |

A dirty tree's commit does not identify its sources, so enforcing it would
brick a dev session on any unrelated commit made between installing the
adapter and rebuilding the worker, while still proving nothing. Release
qualification rejects dirty separately.

Two clean artifacts from different commits ARE refused, because `wire` is not
bumped for every frame change: on one release lineage the commit is the only
thing separating same-shape semantic skew, which is exactly the hazard of the
two-pin delivery model (adapter from PyPI/git, worker from a Lake pin that can
name a different commit). The qualification job asserts the same pair is
`agreed: true` at one candidate SHA, as an independent second gate.

In a working tree a refusal almost always means one half was rebuilt without
the other — the worker re-embeds its identity on every `lake build`, while an
editable install keeps the `_build_info.json` it was installed with. **`just
build` refreshes both together**, which is the remedy; the adapter also says
so on stderr whenever a pair is not verified, rather than leaving an
unverifiable session silent.

Refusal follows the loud-init-failure pattern: the kernel starts and answers
`kernel_info`, and every execute returns a typed `ProvenanceError` naming both
identities. Missing adapter build info behaves the same way — a kernel that
dies before `kernel_info` reports only "Kernel died before replying to
kernel_info", which names neither cause nor fix.

Clients read the compared object — plus the SHA-256 of the executed worker
binary — from the `nbdsl_provenance` Jupyter comm: opening that target
replies `{adapter, worker, worker_binary_sha256, agreed}` on the **opener's
comm_id**.

## Client-side contracts (not wire, but load-bearing)

- The replay ledger (committed `(cell_id, code)` pairs in REPL mode) is the
  canonical recovery record; the session cache is a validated shortcut.
- Killing the worker means `os.killpg` — `lake env` forks the worker, so a
  plain kill only hits the wrapper and a busy worker survives as a spinning
  orphan.
