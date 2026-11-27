# Feature Specification: Worker protocol 2 and the notebook client

**Feature Branch**: none (work lands on `main`)
**Created**: 2026-11-25
**Status**: Ready for planning
**Input**: The part of the lean-cas-dsl notebook session that this repository owns: the worker
and client parts of kernel tasks T083 to T093, T098, T099, T127 and T347, and the notebook launch
of T153, of lean-cas-dsl `specs/001-categorical-research-language/tasks.md`, under the session
contract `contracts/notebook-session.md` ([NS]) and the kernel requirements FR-034 to FR-038,
FR-043, FR-140, SC-010, SC-011 and SC-016 ([KS]); and the Lean language server in Lean notebook
cells of issue #20 (User Story 7), which is outside the notebook unit of lean-cas-dsl.

Source identifiers [NS], [KS], [KT] and [K] are defined in the
[constitution](../../.specify/memory/constitution.md).

## User Scenarios & Testing *(mandatory)*

The actor in every story is a researcher who works in a Jupyter notebook. The notebook runs on
the kernel of this repository, with the CAS plugin of lean-cas-dsl or with a plugin of this
repository.

### User Story 1 - Connected cells that use retained results (Priority: P1)

The researcher runs a cell that computes a result, then runs later cells that use it. Each cell
runs on an explicit committed parent. The later cell uses the retained result of the earlier
cell; nothing runs again.

**Why this priority**: A result that a later cell cannot use does not complete a calculation
([K] C8; [KS] User Story 7).

**Independent Test**: In a real notebook on the installed kernelspec, cell A binds a value and
cell B uses it. With the CAS plugin, the application log shows one dispatch for A and none for
the reuse in B.

**Acceptance Scenarios**:

1. **Given** a started worker, **When** cell A commits and cell B is executed with A's snapshot
   as parent, **Then** B sees A's bindings, B commits a new snapshot whose parent is A's, and A's
   computation is not dispatched again.
2. **Given** a parent snapshot that the live worker does not hold, **When** a cell is executed
   on it, **Then** the reply is `unavailable/snapshot_unavailable` and no preceding cell runs.
3. **Given** a cell with an error-severity diagnostic, **When** it is executed, **Then** the
   reply keeps the parent snapshot, publishes no output, and a later cell on the parent does not
   see any declaration of the failed cell.
4. **Given** a cell that a user executes a second time, **When** it runs, **Then** it is a fresh
   request with a fresh transport ID and a fresh occurrence.
5. **Given** a committed cell `def two : Nat := 2`, **When** a later cell `#guard two == 2` runs on
   its snapshot, **Then** it commits, and the plugin state differs from the parent only by the
   declarations of the two cells.

### User Story 2 - Inspection that executes nothing (Priority: P1)

The researcher asks for inspection, completion or syntax completeness. The answer comes from
committed state. No cell runs, no worker starts, nothing is dispatched.

**Why this priority**: An observation that changes state corrupts the question
([KS] FR-035; [NS] §3.2).

**Independent Test**: With a cell whose execution increments an external counter, inspection,
completion and `is_complete` on a buffer that contains that cell leave the counter, the snapshot
list and the dispatch log unchanged. Against a worker that lacks the protocol-2 features, the
client sends no source.

**Acceptance Scenarios**:

1. **Given** a live compatible worker, **When** `inspect` or `complete` is requested on a
   buffer with unexecuted text, **Then** the answer names only committed declarations and the
   counts of executions, occurrences and dispatches do not change.
2. **Given** no started worker, **When** inspection or completion is requested, **Then** the
   reply is unavailable with reason `worker_absent`, no worker starts, and `is_complete` answers
   `unknown`.
3. **Given** a started worker whose `ready` frame lacks protocol 2, a feature or the profile
   hash, **When** any request is made, **Then** the client reports
   `unavailable/incompatible_protocol` and the worker receives zero bytes of candidate source.
4. **Given** a plugin with a delaborator, a documentation hook or a lazy field that has a side
   effect, **When** inspection reaches a declaration that uses it, **Then** the hook does not run
   on the success path or on the error path.

### User Story 3 - Cancellation (Priority: P1)

The researcher interrupts a running cell. The cell is cancelled, publishes nothing, and earlier
results stay usable. When the cell had already committed, the interrupt reports that.

**Why this priority**: Cancellation must not publish part of a cell or damage prior results
([KS] FR-036; [NS] §3.3).

**Independent Test**: A long cell is interrupted through Jupyter. The reply is cancelled, the
parent snapshot is current, a cell that uses an earlier result still succeeds, and the cell
status carries the drain report.

**Acceptance Scenarios**:

1. **Given** a running cell, **When** cooperative cancellation wins the commit/cancel gate,
   **Then** the reply is `cancelled`, the snapshot is the parent, and no output or reference is
   published.
2. **Given** a cell that committed first, **When** cancellation arrives, **Then** the reply is
   `already_committed` with the actual commit and snapshot.
3. **Given** a queued cell, **When** it is cancelled before its transaction starts, **Then** it
   never starts.
4. **Given** a cancelled cell whose engine frames are still draining, **When** `commit_status`
   is requested, **Then** the status is not `committed` and carries the drain report of the cell.
5. **Given** an unknown target, **When** cancellation is requested, **Then** the reply is
   `not_found` and no occurrence is created.

### User Story 4 - Forced owner replacement (Priority: P2)

The researcher forces a stuck cell to stop. The owners that the force closes are named. A later
use of a result that depends on a closed owner is refused before dispatch. Unrelated results
stay usable.

**Why this priority**: A forced close must not leave a result that silently uses a dead owner
([K] C13; [NS] §3.3).

**Independent Test**: With the CAS plugin, a cell that holds a live engine object is forced. The
reply lists the invalidated owners. A later cell that uses that object fails as unavailable with
no dispatch in the log; a later cell that uses an unrelated stored value succeeds.

**Acceptance Scenarios**:

1. **Given** an active or draining cell, **When** force is requested, **Then** the reply is
   `forced` with the exact invalidated owners.
2. **Given** an invalidated owner, **When** a later cell or an older snapshot uses a dependent
   reference, **Then** the use is unavailable before any external dispatch.

### User Story 5 - Restart with no replay (Priority: P2)

The researcher restarts the kernel. A new worker starts with a fresh nonce and an empty session.
No earlier cell runs again. Saved outputs stay visible as saved document data.

**Why this priority**: Replay after restart changes the question ([K] policy "Retry and
migration").

**Independent Test**: After a restart in a real notebook, an execution counter in an external
file is unchanged, the new nonce differs from the old one, and a cell that uses an old result
fails as unavailable.

**Acceptance Scenarios**:

1. **Given** a session with committed cells, **When** the user restarts, **Then** the worker
   has a fresh nonce, snapshot 0 only, and no cell runs until the user executes one.
2. **Given** a worker that dies, **When** the next cell is executed, **Then** the reply is
   unavailable and no worker starts implicitly; the user restarts explicitly.
3. **Given** a request whose reply is lost after send, **When** the client reports it, **Then**
   the status is `unavailable/connection_lost_after_send` with indeterminate execution, and the
   request is not sent again.

### User Story 6 - Automatic mathematical display, once per event (Priority: P2)

The researcher sees each committed result in mathematical notation automatically, with a usable
text form, once. Diagnostics of backend, routing and timing appear only on request.

**Why this priority**: The display policy of [K] and [KS] FR-038.

**Independent Test**: A cell with two results produces exactly two `display_data` or
`execute_result` messages, each with `text/latex` and `text/plain` in one bundle and the
qualifications of the result. A refresh of the display executes nothing.

**Acceptance Scenarios**:

1. **Given** a committed batch, **When** it is published, **Then** each result is one display
   event with `text/latex` where supplied and `text/plain`.
2. **Given** a failed or cancelled cell, **When** its reply arrives, **Then** no result display
   is published.
3. **Given** the same batch delivered twice, **When** the client receives it, **Then** it
   displays once, deduplicated by batch and result ID.
4. **Given** no request for diagnostics, **When** a cell commits, **Then** no backend, routing or
   timing text is shown.

### User Story 7 - The Lean language server in Lean notebook cells (Priority: P3)

The researcher writes Lean proofs in the cells of a notebook on the `nbdsl` kernelspec or the
native session. While the researcher edits, the real Lean language server gives the goal state,
hover, diagnostics, completion and navigation of the cell under the cursor, as the VS Code Lean
extension does. Execution of a cell still goes through the worker.

**Why this priority**: Proof work needs the live goal state of the text being edited; a REPL
answer after execution does not supply it (issue #20). No notebook requirement of lean-cas-dsl
asks for it, so it is not part of the notebook unit; the kernel's inert-inspection requirement
excludes it from CAS notebooks ([KS] FR-035).

**Independent Test**: In JupyterLab, a notebook holds a Mathlib-backed proof in two cells, the
second using a definition of the first. With neither cell executed, the researcher edits the first
cell, moves the cursor into the proof of the second and reads its goal and hover for the current
text; inserts lines in the first cell, reorders the cells and applies a suggestion of the
infoview. Diagnostics, goals and the insertion map to the right cell and position, also after a
server restart and after the panel is hidden and shown again. The worker log shows no request
from these steps.

**Acceptance Scenarios**:

1. **Given** a Lean notebook with the language-server channel on, **When** the cursor is in a
   proof, **Then** the infoview shows the goal state of the current cell text at that position.
2. **Given** an edit of an earlier cell that is not executed, **When** the cursor moves into a
   later cell that uses it, **Then** hover and diagnostics follow the edited text.
3. **Given** a suggestion applied from the infoview, **When** it is inserted, **Then** it lands in
   the cell and at the position that the server names.
4. **Given** the channel on, **When** Jupyter sends `inspect`, `complete` or `is_complete`,
   **Then** the worker answers from committed state (FR-005) and the language server takes no
   part.
5. **Given** a notebook on the `casdsl` kernelspec, **When** the researcher edits a cell, **Then**
   no cell text reaches a language server.

### Edge Cases

- A repeated transport ID with an equal payload, a changed payload or a different operation
  receives the duplicate diagnostic; the original execution is not settled by it.
- A request with a nonce of an earlier worker is rejected without evaluation and consumes no ID.
- A cancellation with a mode other than `cooperative` or `force` is a protocol error.
- A cell executed while another cell is active waits in the queue; only one mutating
  transaction runs.
- An unacknowledged cancellation reports `unavailable/cancel_unacknowledged`; no forced kill
  follows without a request.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001 — Protocol-2 startup.** On explicit start, the worker emits `ready` with protocol 2,
  `release`, `lean`, `pid`, a fresh `worker_nonce`, `snapshot "0"`, `realization_profile` with
  `id` and `sha256`, and exactly the features `cas-session/2`, `explicit-parent/2`,
  `atomic-cell/2`, `inspect-environment/2`, `complete-environment/2`, `cancel-by-request/2`,
  `no-replay/2`, `no-session-cache/2`. Before the `hello` acknowledgement the worker accepts only
  `hello`, `version` and `shutdown`. ([NS] §2; [KT] T083.)
- **FR-002 — Handshake validation before source.** The client validates protocol, all eight
  features, the nonce, the policy `cas_no_replay` and the frozen profile hash against the
  recorded configuration before it serializes any request that carries source. A mismatch is
  `unavailable/incompatible_protocol` with zero source bytes sent. ([NS] §2; [KT] T084.)
- **FR-003 — Request header and ID admission.** Every post-handshake request carries
  `protocol: 2`, a fresh `request_id`, the actual `worker_nonce` and `op`. The worker claims
  `(nonce, request_id)` atomically before operation-specific validation. A repeat receives
  exactly `{"op":"protocol_error","worker_nonce":…,"offending_request_id":…,"reason":"duplicate_request_id"}`
  and nothing else. A foreign nonce is rejected without consuming an ID. ([NS] §3, §3.0;
  [KT] T083, T091.)
- **FR-004 — Explicit-parent execution, one queued transaction.** `execute` names `cell_id`,
  `parent_snapshot` and `session_policy`. One mutating transaction is active per worker; others
  queue with their parents. A missing parent gives `status: "unavailable"` with reason
  `snapshot_unavailable`. The client always sends an explicit parent. ([NS] §1, §3.1;
  [KT] T085.)
- **FR-005 — Data-only queries.** `inspect` and `complete` use environment mode and read
  prepared immutable descriptors of a committed snapshot with non-extensible lookup and
  formatting. `is_complete` uses syntax mode and fixed tokenization. No query elaborates
  candidate text or calls an extensible hook. A query consumes its transport ID and changes no
  other state. ([NS] §3.2; [KT] T086.)
- **FR-006 — Query guards.** With no live worker, the client answers `unavailable/worker_absent`
  for inspect and complete and `unknown` for `is_complete`, and starts nothing. With an
  incompatible or unacknowledged worker it answers `unavailable/incompatible_protocol` and
  sends no source. With a stale snapshot it answers `unavailable/snapshot_unavailable`. ([NS] §2,
  §3.2; [KT] T087.)
- **FR-007 — Source-free cancellation and one gate.** `cancel` names `target_request_id` and
  `mode` (`cooperative` or `force`). The worker handles it outside the evaluator. The commit and
  cancel decisions share one linearization point. Replies: `cancelled`, `already_committed` with
  the commit, `not_found`, or `forced` with `invalidated_owners`. ([NS] §3.3; [KT] T088.)
- **FR-008 — Cooperative drain and its report.** After cooperative cancellation the worker keeps
  the permit of the cell until its exact in-flight frames drain, schedules no late child or
  resume, and publishes nothing. The drain report of the cell (draining, drained, or
  unacknowledged cleanup with its failures) is carried in the cell status of `commit_status` and in the reply to a cooperative `cancel`.
  ([NS] §3.3; [KT] T089, which connects `FramedConnection.cleanupFailures` to the drain report of
  the cell, and T091.)
- **FR-009 — Force, close and generation invalidation.** Explicit force closes the connections
  of the target and reports the exact invalidated owners. Shutdown, restart and transport
  failure report generation loss. A later use of a dependent reference is unavailable before
  dispatch, also from an older snapshot. ([NS] §3.3, §4; [KT] T090.)
- **FR-010 — Committed status.** `commit_status` names `target_request_id` and a committed
  `snapshot`. It returns `committed` only from a receipt visible in that snapshot, `pending` only
  for current active work, and otherwise `unavailable`. Staged work is pending. It carries the
  drain report of FR-008. ([NS] §3.3; [KT] T091.)
- **FR-011 — Atomic publication.** A successful reply carries the complete committed batch:
  `commit` with `transaction_id`, `output_batch_id`, `profile_sha256`, `result_refs`, and
  `outputs` whose entries have a unique `result_id` and a MIME bundle. A failed or cancelled
  reply has `snapshot = parent_snapshot`, empty outputs and no commit. Nothing streams before
  commit. ([NS] §3.1, §4; [KT] T092.)
- **FR-012 — No implicit restart, replay or prefix execution.** The client and the kernel
  adapter contain no replay ledger, no session cache, no prefix execution, no restart on worker
  death and no `restart_and_replay`. An explicit restart starts a fresh worker with a fresh nonce.
  ([NS] §1; [KT] T093.)
- **FR-013 — Automatic display.** The client publishes each committed result once, with
  `text/latex` where supplied and `text/plain`, with its qualifications, deduplicated by batch
  and result ID. A refresh reads retained data only. Diagnostics are opt-in. ([KS] FR-038;
  [KT] T099.)
- **FR-014 — Logs and timing records.** The worker and the client write a JSON-lines application
  log per session: for each request, its ID, operation, parent, transaction, outcome, commit or
  failure, published batch and elapsed time. Each test run writes a log under
  `records/test-runs/` and a timing record per test under `records/timing/` with run, revision,
  environment, input and phases. ([KS] FR-043, SC-016; constitution E6, E7.)
- **FR-015 — Toolchain alignment.** The worker and `dsls/nbdsl` build with the Lean toolchain and
  Mathlib revision that lean-cas-dsl `main` pins. (Constitution J9.)
- **FR-016 — Tier-1 commit gate.** The commit hook runs tier 1 (constitution E1) within 300
  seconds; the full gate runs at push. (Constitution E1, E4.)
- **FR-017 — Lean commands in cells.** An ordinary Lean command in a cell elaborates as Lean in the
  environment of the session, through the plugin, and changes the plugin state only through the
  declarations that it adds. ([KS] FR-140; [KT] T347.)
- **FR-018 — Language-server channel.** For the Lean cells of a notebook on the `nbdsl` kernelspec
  or the native session, a JupyterLab channel drives the Lean language server (`lake serve`) of the
  notebook's Lean project on one language-server document: the Lean cells in cell order, with a map
  from each cell to its line range. It gives goal state, hover, diagnostics, completion and
  navigation, and it hosts the upstream infoview through its host API (`EditorApi` and
  `InfoviewApi` of `@leanprover/infoview`): it relays the subscribed notifications in both
  directions, sends cursor changes, maps edits and navigation back to the cells, and keeps the RPC
  session alive. The researcher turns the channel on for a notebook (constitution J4). (Issue #20;
  research R10.)
- **FR-019 — The channel and the kernel stay apart.** The language-server channel answers no
  kernel request: `inspect`, `complete` and `is_complete` stay worker answers from committed
  state (FR-005; constitution J1, J5). The channel sends no request to the worker and changes no
  snapshot, occurrence or dispatch. On the `casdsl` kernelspec the channel is off and no cell text
  reaches a language server: the server elaborates uncommitted text, the elaboration of a CAS cell
  dispatches computations, and an endpoint without nonexecuting committed-environment inspection
  receives no executable cell text ([KS] User Story 7, scenario 2, and FR-035; [NS] §3.2).
- **FR-020 — Contribution lessons.** `CONTRIBUTING.md` holds the lessons of past mistakes as
  policies with stable IDs in categories; each policy shows a defective contribution beside its
  replacement. (Constitution E3.)
- **FR-021 — Documents of protocol 2.** The README, `docs/` and the extension README describe
  protocol 2. No document gives replay, a session cache, protocol 1 or an implicit restart as
  behaviour of this repository. ([NS] §1; plan, disagreement N7.)
- **FR-022 — Release.** A tagged release `v2.0.0` of `main` is the immutable worker revision that
  lean-cas-dsl locks for `nbdsl-worker`. ([KT] T093.)
- **FR-023 — Consumer qualification.** Tier 3 runs CAS cells through the installed worker and a
  real `KernelSession` of lean-cas-dsl at a pinned revision with the toolchain of FR-015: a
  retained value used in a later cell, a missing parent, a forced owner and an inert inspection.
  (Constitution E1; [KT] T093, T153.)

### Key Entities

- **Worker session**: one process, one nonce, the realization profile, the snapshot list and the
  used-ID set.
- **Snapshot**: an immutable committed environment with a decimal serial scoped to the nonce.
- **Cell transaction**: one active mutating execution with its parent, its staged completions and
  its drain report.
- **Committed receipt**: the commit of a transaction, visible in the snapshots that contain it.
- **Output batch**: the complete set of result displays of one commit.
- **Language-server document**: the Lean cells of one notebook in cell order, the map from each
  cell to its line range, and the server session of the channel; separate from the worker
  session.

## Success Criteria *(mandatory)*

### Measurable Outcomes

| ID | Outcome | Measure |
| --- | --- | --- |
| SC-001 | Connected cells use retained results | In the notebook test, 0 re-dispatches of an earlier cell; every later cell commits on its explicit parent |
| SC-002 | Queries are inert | Over all query controls (live, missing, stale, incompatible worker): 0 executions, 0 occurrences, 0 dispatches, 0 worker starts; 0 source bytes to an incompatible worker ([KS] SC-011) |
| SC-003 | Cancellation publishes nothing | 0 outputs and 0 references from a cancelled cell; 100% of prior results still usable |
| SC-004 | Force invalidates exactly | 0 usable dependent references after force; 0 stale external dispatches, also from an old snapshot |
| SC-005 | No replay | 0 automatic retries, replays or restarts over the lifecycle suite |
| SC-006 | Duplicate IDs | 100% of identical, changed and cross-operation repeats rejected; 0 original executions settled by the diagnostic |
| SC-007 | Display once | Exactly 1 display event per committed result; 0 diagnostics shown without request ([KS] SC-010) |
| SC-008 | Records | Every test run has a log and every test has a timing record in the repository ([KS] SC-016) |
| SC-009 | Fast loop | Tier 1 finishes within 300 seconds on the development host |
| SC-010 | Language server in Lean cells | In the two-cell specimen of User Story 7, goal, hover, diagnostics and insertion map to the right cell and position at every step, also after a server restart and a hidden panel; 0 worker requests from these steps; 0 bytes of `casdsl` cell text to a language server |

## Assumptions

- The CAS plugin, `KernelSession`, its transactions, owners and drain report are supplied by
  lean-cas-dsl tasks T009, T011, T013, T021 to T023, T038 and T089. This repository carries them
  across the wire.
- The lifecycle validation phase `lifecycle-v2` and the final notebook acceptance (lean-cas-dsl
  T094, T095, T102, T107) are run by the independent assessor in lean-cas-dsl against a build of
  this repository.
- The Lean project of the language-server channel is `dsls/nbdsl`, Mathlib-backed and built in the
  research image on the toolchain of FR-015.
