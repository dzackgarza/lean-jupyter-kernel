# Tasks: Worker protocol 2 and the notebook client

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/wire-protocol-2.md](contracts/wire-protocol-2.md)

## Execution order

Execute the unchecked tasks in document order (constitution, "Work order"). Each task names its
files, its acceptance, the lean-cas-dsl task that it supplies or consumes (prefix `K:`) and its
inputs. Every test is end to end: a real cell through the production client or the installed
kernelspec, through the real worker (constitution E2). Tier-1 tests use the native mathlib-free
plugin `Worker/NativeSession.lean`; tier-3 tests use a real `KernelSession` of lean-cas-dsl.

Format: `[ID] [Story] Description`. A task with no story serves every story.

## Phase 1: Feedback and records

- [ ] T001 Create `CONTRIBUTING.md` with policies under stable IDs in categories `TEST`,
  `WIRE`, `LIFE` and `DOC`. Seed them from `docs/development.md:61-65` (reply matching by
  `parent_header.msg_id`; no test that depends on module order) and `docs/dsl.md:104-116`
  (parser notes), and add `LIFE001`: recovery by replay or session cache after worker loss ⇒
  report unavailable and wait for an explicit restart. Each policy shows a defective
  contribution beside its replacement. Point `docs/development.md` and `AGENTS.md` to it.
  **Acceptance**: every policy has an ID, a category, a defective example and its replacement.
  **Supplies**: none. **Inputs**: constitution E3.
- [ ] T002 Add the tier-1 gate and the test records. In `justfile`, add `test-tier1` (research
  R7) and make `test-commit` run it; `test-push` and `test-ci` run `test`. Add
  `nbdsl_kernel/tests/conftest.py` and a writer in `nbdsl_kernel/tests/roundtrip.py` that write
  `records/test-runs/<run-id>/log.txt` and `records/timing/<run-id>.jsonl` (research R6). Create
  `records/README.md` that states the layout. Update the suite table of `docs/development.md`
  with the tier of each suite.
  **Acceptance**: `just test-tier1` finishes within 300 s on the development host and leaves one
  log and one timing line per test with all fields of research R6; the commit hook runs tier 1
  only. **Supplies**: K FR-043 for the notebook part of the test records. **Inputs**:
  constitution E1, E4, E6, E7.

## Phase 2: Publication and toolchain

- [ ] T003 Land the eight local protocol-2 commits on `main` (plan, "The eight local
  protocol-2 commits"). In the worktree of branch `integration/kernel-v1-20261106`, merge
  `origin/main` with a forward merge commit. Resolve the conflicts in
  `worker/Worker/Frontend.lean`, `nbdsl_kernel/tests/roundtrip.py`, `justfile`,
  `.github/workflows/ci.yml`, `README.md`, `docs/protocol.md`, `docs/development.md` and
  `AGENTS.md` so that the trivia-only cell fix of 819849d, protocol 2 and the constitution all
  hold. Push to `main` as a fast-forward; rewrite no commit.
  **Acceptance**: `origin/main` contains fc043aa to c914cd1 and 819849d; tier 1 and tier 2 pass
  on the merge; fb03325 resolves on GitHub. **Supplies**: K:T083, K:T084, the worker side of
  K:T085 and K:T086, K:T092, the client part of K:T099; the lock fb03325 of the lean-cas-dsl
  kernel branch. **Inputs**: T002.
- [ ] T004 Align the toolchain (research R8). Set `leanprover/lean4:v4.36.0-rc2` in
  `release.toml`, `worker/lean-toolchain` and `dsls/nbdsl/lean-toolchain`; set Mathlib `master`
  at 5d0d3c0 in `dsls/nbdsl/lakefile.lean` and its `lake-manifest.json`; repair the worker
  sources that the Lean change breaks.
  **Acceptance**: tier 1 and tier 2 pass on v4.36.0-rc2; `ready.lean` reports the new version.
  **Supplies**: lean-cas-dsl issue #90 (the port of its kernel branch to the research-image
  pins). **Inputs**: T003; the lean-cas-dsl `main` pins.

## Phase 3: User Story 1 - Connected cells that use retained results (P1)

- [ ] T005 [US1] Make every execution name its parent and reply `unavailable` for a missing
  parent. In `worker/Worker.lean` (`execute`, `failedExecution`), reply research R1. In
  `nbdsl_kernel/nbdsl_kernel/worker/client.py` remove `execute` without a parent; in
  `nbdsl_kernel/nbdsl_kernel/kernel.py` (`_execute_once`, `_run_init_cell`) compute the parent of
  research R4 for every path. Add the tests to `nbdsl_kernel/tests/test_native_v2.py`: A binds,
  B on A's snapshot uses it, a missing parent is unavailable and runs nothing, a failed cell
  keeps its parent.
  **Acceptance**: User Story 1 scenarios 1 to 4 pass in tier 1. **Supplies**: K:T085, K:T087.
  **Inputs**: T003.

## Phase 4: User Story 2 - Inspection that executes nothing (P1)

- [ ] T006 [US2] Complete the query guards and the error paths. In `kernel.py` and
  `handlers.py`, answer `unavailable/worker_absent` for inspect and complete with no worker and
  start nothing. In `worker/Worker.lean` (`handle`, `query`) answer research R2 for unknown
  operations and modes. In `worker/Worker/Query.lean`, confirm that no success path or error
  path calls `Meta.ppExpr`, a delaborator, a documentation callback or a lazy field. Add a
  side-effecting delaborator and a documentation hook to a test prelude in
  `nbdsl_kernel/tests/test_request_controls.py` and assert that inspection does not run them.
  **Acceptance**: User Story 2 scenarios 1 to 4 pass in tier 1; zero source bytes reach an
  incompatible worker (`test_identity.py`). **Supplies**: K:T086, K:T087. **Inputs**: T005.

## Phase 5: User Story 3 - Cancellation (P1)

- [ ] T007 [US3] Test the commit/cancel gate through Jupyter interrupts. In
  `nbdsl_kernel/tests/test_request_controls.py` add: a queued cell cancelled before it starts; a
  cell that commits before the cancel (`already_committed` with its commit); an unknown target
  (`not_found`); an invalid mode (protocol error); a repeated transport ID with an identical
  payload, a changed payload and a different operation, each answered by the duplicate
  diagnostic while the original execution still settles with its own reply. Repair `worker/Worker.lean` (`cancel`) where
  a test fails.
  **Acceptance**: User Story 3 scenarios 1, 2, 3 and 5 and the duplicate-ID edge cases pass in
  tier 1. **Supplies**: K:T088, the duplicate-ID part of K:T091.
  **Inputs**: T005.
- [ ] T008 [US3] [US4] Carry the drain report and force invalidation. Replace
  `Active.draining : BaseIO Bool` in `worker/Worker/Cell.lean` with `drainReport` (research R3);
  carry `drain` in `commitStatus` and the cooperative `cancel` reply of `worker/Worker.lean`;
  model it in `nbdsl_kernel/nbdsl_kernel/protocol.py`; implement it in
  `worker/Worker/NativeSession.lean`. Add tests to `nbdsl_kernel/tests/test_native_session.py`:
  a cancelled draining cell reports `draining`, then `drained`; force returns the exact
  invalidated owners and a later use of a dependent reference is unavailable before dispatch.
  **Acceptance**: User Story 3 scenario 4 and User Story 4 scenarios 1 and 2 pass in tier 1 with
  the native plugin. **Supplies**: the wire part of K:T089, K:T090, K:T091. **Consumes**:
  K:T089 supplies `CellTransaction.draining` and `FramedConnection.cleanupFailures` for the CAS
  plugin. **Inputs**: T007.

## Phase 6: User Story 5 - Restart with no replay (P2)

- [ ] T009 [US5] Remove implicit restart and replay. Delete `restart_and_replay` from
  `worker/client.py` and every caller; keep `restart_fresh` as the explicit restart; make worker
  death answer unavailable with no implicit start in `kernel.py`. Rewrite
  `nbdsl_kernel/tests/test_restart.py` to assert: a fresh nonce after restart, snapshot 0 only,
  an unchanged external execution counter, an old reference unavailable, and a lost reply
  reported as `unavailable/connection_lost_after_send` with no resend.
  **Acceptance**: User Story 5 scenarios 1 to 3 pass in tier 1; no symbol of replay, ledger or
  session cache remains in `nbdsl_kernel/` or `worker/`. **Supplies**: K:T093. **Inputs**: T008.

## Phase 7: User Story 6 - Automatic display once per event (P2)

- [ ] T010 [US6] Test one emission per result end to end. In `nbdsl_kernel/tests/test_e2e.py`,
  run a cell with two results through the installed kernelspec and count exactly two display
  messages, each with `text/latex` and `text/plain` in one bundle; a duplicated batch displays
  once; a failed cell displays nothing; no backend, routing or timing text appears. Repair
  `cas_display.py`, `rendering.py` or `handlers.py` where a test fails.
  **Acceptance**: User Story 6 scenarios 1 to 4 pass in tier 2 and the deduplication test in
  `test_cas_display.py` passes in tier 1. **Supplies**: K:T099. **Consumes**: K:T092 (the CAS
  batch with its qualifications) for tier 3. **Inputs**: T009.

## Phase 8: Cross-cutting

- [ ] T011 Write the application logs (research R5). Add `--log-file` to the worker arguments in
  `worker/Worker.lean` and write one record per request; write the client records in
  `worker/client.py`; pass the paths from `kernel.py` and `install.py`. Add a tier-1 test that
  runs connected cells and reads both logs.
  **Acceptance**: for each request the logs hold every field of research R5; the notebook shows
  none of it. **Supplies**: K FR-043 (the worker part of the application log). **Inputs**:
  T010.
- [ ] T012 [US1] [US4] Qualify against a real `KernelSession`. Pin `scripts/qualify_consumer.sh`
  to the lean-cas-dsl revision of research R9 and replace the `sage -python` start; add a
  qualification notebook in `conformance/` with CAS cells: a retained value used in a later cell
  with one dispatch in the application log; a forced owner whose dependent use is unavailable;
  inspection with zero dispatches. Update `conformance/README.md` and the `casdsl` row of
  `conformance/test_semantic.py`.
  **Acceptance**: tier 3 passes on the pinned revision. **Consumes**: K:T038, K:T085, K:T090.
  **Supplies**: the notebook path of the M1.9 checkpoint (K:T093). **Inputs**: T011.
- [ ] T013 Bring the documents into agreement with protocol 2: `docs/protocol.md` (the frames of
  `contracts/wire-protocol-2.md`), `docs/architecture.md`, `docs/plugins.md` (remove the
  replayability law at `:34` and the `unsupported` seam), `README.md` (limits and verify
  section), `jupyterlab_nbdsl/README.md` (the word lists follow the lean-cas-dsl reader of
  `CasCompiler/`), the `justfile` header.
  **Acceptance**: no document describes replay, a session cache, protocol 1 or an implicit
  restart. **Supplies**: none. **Inputs**: T011.
- [ ] T014 Release 2.0.0. Set `release.version = "2.0.0"` in `release.toml`, run
  `scripts/release_projection.py`, tag `v2.0.0` on `main`.
  **Acceptance**: the release workflow publishes `v2.0.0`. **Supplies**: the immutable pin that
  lean-cas-dsl locks for `nbdsl-worker` (K:T093 and issue #90). **Inputs**: T013.

## Dependencies

| Task | Inputs |
| --- | --- |
| T001 | none |
| T002 | none |
| T003 | T002 |
| T004 | T003 |
| T005 | T003 |
| T006 | T005 |
| T007 | T005 |
| T008 | T007 |
| T009 | T008 |
| T010 | T009 |
| T011 | T010 |
| T012 | T011; K:T038, K:T085, K:T090 |
| T013 | T011 |
| T014 | T012, T013 |

A wait for a lean-cas-dsl task blocks only T012; the contributor continues with T013 and keeps
T012 in its position.

## Coverage

| Requirement | Tasks |
| --- | --- |
| FR-001, FR-002, FR-011 | T003 |
| FR-003 | T003, T007 |
| FR-004 | T005 |
| FR-005, FR-006 | T006 |
| FR-007 | T007 |
| FR-008, FR-009, FR-010 | T008 |
| FR-012 | T009 |
| FR-013 | T010 |
| FR-014 | T002, T011 |
| FR-015 | T004 |
| FR-016 | T002 |

| Success criterion | Tasks |
| --- | --- |
| SC-001 | T005, T012 |
| SC-002 | T006 |
| SC-003 | T007, T008 |
| SC-004 | T008, T012 |
| SC-005 | T009 |
| SC-006 | T007 |
| SC-007 | T010 |
| SC-008 | T002, T011 |
| SC-009 | T002 |
