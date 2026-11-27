# Tasks: Worker protocol 2 and the notebook client

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/wire-protocol-2.md](contracts/wire-protocol-2.md)

## Execution order

Execute the unchecked tasks in document order (constitution, "Work order"). Each task names its
files, one check, its acceptance, the lean-cas-dsl task that it supplies or consumes (prefix `K:`)
and its inputs. A task is done when its check passes and its acceptance holds. Each check follows
the check-route rule of lean-cas-dsl `CONTRIBUTING.md` (SPEC004); the commands are those of the
[quickstart](quickstart.md). Every test is end to end: a real cell through the production client
or the installed kernelspec, through the real worker (constitution E2). Tier-1 tests use the
native mathlib-free plugin `Worker/NativeSession.lean`; tier-3 tests use a real `KernelSession` of
lean-cas-dsl.

Format: `[ID] [Story] Description`. A task with no story serves every story. Task IDs are stable:
lean-cas-dsl names them, so a new task takes the next free ID at its place in the order.

## Phase 1: Contribution lessons, publication and records

- [ ] T001 Create `CONTRIBUTING.md` with policies under stable IDs in categories `TEST`,
  `WIRE`, `LIFE` and `DOC` (FR-020). Seed them from `docs/development.md:61-65` (reply matching
  by `parent_header.msg_id`; no test that depends on module order) and `docs/dsl.md:104-116`
  (parser notes), and add `LIFE001`: recovery by replay or session cache after worker loss ⇒
  report unavailable; only an explicit restart starts a worker. Each policy shows a defective
  contribution beside its replacement. Point `docs/development.md` and `AGENTS.md` to it.
  **Files**: `CONTRIBUTING.md` (new), `docs/development.md`, `AGENTS.md`.
  **Check**: `grep -n -E '\b(TEST|WIRE|LIFE|DOC)[0-9]{3}\b' CONTRIBUTING.md` lists every policy;
  each listed policy has a defective example beside its replacement; `docs/development.md` and
  `AGENTS.md` link `CONTRIBUTING.md`.
  **Acceptance**: every policy has an ID, a category, a defective example and its replacement.
  **Supplies**: none. **Inputs**: none (constitution E3).
- [ ] T003 Land the eight local protocol-2 commits on `main` (plan, "The eight local
  protocol-2 commits"). In the worktree of branch `integration/kernel-v1-20261106`, merge
  `origin/main` with a forward merge commit. Resolve the conflicts so that the trivia-only cell
  fix of 819849d, protocol 2 and the constitution all hold. Push to `main` as a fast-forward;
  rewrite no commit.
  **Files**: `worker/Worker/Frontend.lean`, `nbdsl_kernel/tests/roundtrip.py`, `justfile`,
  `.github/workflows/ci.yml`, `README.md`, `docs/protocol.md`, `docs/development.md`, `AGENTS.md`.
  **Check**: in that worktree, the repository QC gate `just test` passes on the merge commit; after
  the push, `git merge-base --is-ancestor fb03325 origin/main` and
  `git merge-base --is-ancestor 819849d origin/main` succeed.
  **Acceptance**: `origin/main` contains fc043aa to c914cd1 and 819849d; fb03325 resolves on
  GitHub. **Supplies**: K:T083, K:T084, the worker side of K:T085 and K:T086, K:T092, the client
  part of K:T099; the lock fb03325 of the lean-cas-dsl kernel branch. **Inputs**: none.
- [ ] T002 Add the tier-1 gate and the test records (FR-014, FR-016). In `justfile`, add
  `test-tier1` (research R7) and make `test-commit` run it; `test-push` and `test-ci` run `test`.
  Add `nbdsl_kernel/tests/conftest.py` and a writer in `nbdsl_kernel/tests/roundtrip.py` that write
  `records/test-runs/<run-id>/log.txt` and `records/timing/<run-id>.jsonl` (research R6). Create
  `records/README.md` that states the layout. Update the suite table of `docs/development.md`
  with the tier of each suite.
  **Files**: `justfile`, `nbdsl_kernel/tests/conftest.py` (new), `nbdsl_kernel/tests/roundtrip.py`,
  `records/README.md` (new), `docs/development.md`.
  **Check**: `just test-tier1` finishes within 300 s on the development host and leaves one log
  and one timing line per test with all fields of research R6; `just --show test-commit` names
  `test-tier1` only.
  **Acceptance**: the commit hook runs tier 1 only. **Supplies**: K FR-043 for the notebook part
  of the test records. **Inputs**: T003, which puts the native mathlib-free plugin and its tier-1
  client tests (`test_native_v2.py`, `test_request_controls.py`, `test_native_session.py`) on
  `main`.

## Phase 2: Toolchain

- [ ] T004 Align the toolchain (FR-015; research R8). Set `leanprover/lean4:v4.36.0-rc2` in
  `release.toml`, `worker/lean-toolchain` and `dsls/nbdsl/lean-toolchain`; set Mathlib `master`
  at 5d0d3c0 in `dsls/nbdsl/lakefile.lean` and its `lake-manifest.json`; repair the worker
  sources that the Lean change breaks.
  **Files**: `release.toml`, `worker/lean-toolchain`, `dsls/nbdsl/lean-toolchain`,
  `dsls/nbdsl/lakefile.lean`, `dsls/nbdsl/lake-manifest.json`, the `worker/` sources that the
  change breaks.
  **Check**: `just test-tier1` and `just test` pass on v4.36.0-rc2, and the `ready` frame of the
  built worker has `"lean":"4.36.0-rc2"`.
  **Acceptance**: the worker and NbDsl build on the pins of lean-cas-dsl `main`. **Supplies**: the
  worker at the toolchain of the ported kernel, which K:T093 locks through the release of T014.
  **Consumes**: K:T352, the port of the lean-cas-dsl kernel branch to the research-image pins
  (lean-cas-dsl issue #90). **Inputs**: T002, T003; K:T352, done first in lean-cas-dsl.

## Phase 3: User Story 1 - Connected cells that use retained results (P1)

- [ ] T005 [US1] Make every execution name its parent and reply `unavailable` for a missing
  parent. In `worker/Worker.lean` (`execute`, `failedExecution`), reply research R1. In
  `nbdsl_kernel/nbdsl_kernel/worker/client.py` remove `execute` without a parent; in
  `nbdsl_kernel/nbdsl_kernel/kernel.py` (`_execute_once`, `_run_init_cell`) compute the parent of
  research R4 for every path. Add the tests to `nbdsl_kernel/tests/test_native_v2.py`: A binds,
  B on A's snapshot uses it, a missing parent is unavailable and runs nothing, a failed cell
  keeps its parent.
  **Files**: `worker/Worker.lean`, `nbdsl_kernel/nbdsl_kernel/worker/client.py`,
  `nbdsl_kernel/nbdsl_kernel/kernel.py`, `nbdsl_kernel/tests/test_native_v2.py`.
  **Check**: `uv run --project nbdsl_kernel pytest nbdsl_kernel/tests/test_native_v2.py`.
  **Acceptance**: User Story 1 scenarios 1 to 4 pass in tier 1. **Supplies**: K:T085, K:T087.
  **Inputs**: T003.
- [ ] T015 [US1] Elaborate ordinary Lean commands in cells (FR-017; research R11). In
  `worker/Worker/Frontend.lean` and `worker/Worker.lean` (`execute`), elaborate an ordinary Lean
  command of a cell in the environment of its parent snapshot, through the plugin, and commit its
  declarations with the cell; `worker/Worker/NativeSession.lean` keeps its state unchanged apart
  from them. Add the test to `nbdsl_kernel/tests/test_native_v2.py`: a cell `def two : Nat := 2`,
  then a cell `#guard two == 2` on its snapshot.
  **Files**: `worker/Worker/Frontend.lean`, `worker/Worker.lean`,
  `worker/Worker/NativeSession.lean`, `nbdsl_kernel/tests/test_native_v2.py`.
  **Check**: `uv run --project nbdsl_kernel pytest nbdsl_kernel/tests/test_native_v2.py`.
  **Acceptance**: User Story 1 scenario 5 passes in tier 1. **Supplies**: the worker part of
  K:T347. **Inputs**: T005.

## Phase 4: User Story 2 - Inspection that executes nothing (P1)

- [ ] T006 [US2] Complete the query guards and the error paths. In `kernel.py` and
  `handlers.py`, answer `unavailable/worker_absent` for inspect and complete with no worker and
  start nothing. In `worker/Worker.lean` (`handle`, `query`) answer research R2 for unknown
  operations and modes. In `worker/Worker/Query.lean`, confirm that no success path or error
  path calls `Meta.ppExpr`, a delaborator, a documentation callback or a lazy field. Add a
  side-effecting delaborator and a documentation hook to a test prelude in
  `nbdsl_kernel/tests/test_request_controls.py` and assert that inspection does not run them.
  **Files**: `nbdsl_kernel/nbdsl_kernel/kernel.py`, `nbdsl_kernel/nbdsl_kernel/handlers.py`,
  `worker/Worker.lean`, `worker/Worker/Query.lean`, `nbdsl_kernel/tests/test_request_controls.py`.
  **Check**: `uv run --project nbdsl_kernel pytest nbdsl_kernel/tests/test_request_controls.py
  nbdsl_kernel/tests/test_identity.py`.
  **Acceptance**: User Story 2 scenarios 1 to 4 pass in tier 1; zero source bytes reach an
  incompatible worker (`test_identity.py`). **Supplies**: K:T084, K:T086, K:T087, and the worker
  part of K:T098 (non-extensible formatting of the plugin's descriptors in `Query.lean` on the
  success and error paths). **Inputs**: T005.

## Phase 5: User Story 3 - Cancellation (P1)

- [ ] T007 [US3] Test the commit/cancel gate through Jupyter interrupts. In
  `nbdsl_kernel/tests/test_request_controls.py` add: a queued cell cancelled before it starts; a
  cell that commits before the cancel (`already_committed` with its commit); an unknown target
  (`not_found`); an invalid mode (protocol error); a repeated transport ID with an identical
  payload, a changed payload and a different operation, each answered by the duplicate
  diagnostic while the original execution still settles with its own reply. Repair
  `worker/Worker.lean` (`cancel`) where a test fails.
  **Files**: `nbdsl_kernel/tests/test_request_controls.py`, `worker/Worker.lean`.
  **Check**: `uv run --project nbdsl_kernel pytest nbdsl_kernel/tests/test_request_controls.py`.
  **Acceptance**: User Story 3 scenarios 1, 2, 3 and 5 and the duplicate-ID edge cases pass in
  tier 1. **Supplies**: K:T088, the duplicate-ID part of K:T091. **Inputs**: T005.
- [ ] T008 [US3] [US4] Carry the drain report and force invalidation. Replace
  `Active.draining : BaseIO Bool` in `worker/Worker/Cell.lean` with `drainReport` (research R3);
  carry `drain` in `commitStatus` and the cooperative `cancel` reply of `worker/Worker.lean`;
  model it in `nbdsl_kernel/nbdsl_kernel/protocol.py`; implement it in
  `worker/Worker/NativeSession.lean`. Add tests to `nbdsl_kernel/tests/test_native_session.py`:
  a cancelled draining cell reports `draining`, then `drained`; force returns the exact
  invalidated owners and a later use of a dependent reference is unavailable before dispatch.
  **Files**: `worker/Worker/Cell.lean`, `worker/Worker.lean`, `nbdsl_kernel/nbdsl_kernel/protocol.py`,
  `worker/Worker/NativeSession.lean`, `nbdsl_kernel/tests/test_native_session.py`.
  **Check**: `uv run --project nbdsl_kernel pytest nbdsl_kernel/tests/test_native_session.py`.
  **Acceptance**: User Story 3 scenario 4 and User Story 4 scenarios 1 and 2 pass in tier 1 with
  the native plugin. **Supplies**: the wire part of K:T089, K:T090, K:T091; K:T089 and K:T090 run
  these tests through the CAS plugin. **Inputs**: T007.

## Phase 6: User Story 5 - Restart with no replay (P2)

- [ ] T009 [US5] Remove implicit restart and replay. Delete `restart_and_replay` from
  `worker/client.py` and every caller; keep `restart_fresh` as the explicit restart; make worker
  death answer unavailable with no implicit start in `kernel.py`. Rewrite
  `nbdsl_kernel/tests/test_restart.py` to assert: a fresh nonce after restart, snapshot 0 only,
  an unchanged external execution counter, an old reference unavailable, and a lost reply
  reported as `unavailable/connection_lost_after_send` with no resend.
  **Files**: `nbdsl_kernel/nbdsl_kernel/worker/client.py`, `nbdsl_kernel/nbdsl_kernel/kernel.py`,
  `nbdsl_kernel/tests/test_restart.py`.
  **Check**: `uv run --project nbdsl_kernel pytest nbdsl_kernel/tests/test_restart.py`, then
  `grep -rn -E 'replay|ledger|SessionCache|session_cache' nbdsl_kernel/ worker/` prints nothing.
  **Acceptance**: User Story 5 scenarios 1 to 3 pass in tier 1. **Supplies**: K:T093.
  **Inputs**: T008.

## Phase 7: User Story 6 - Automatic display once per event (P2)

- [ ] T010 [US6] Test one emission per result end to end. In `nbdsl_kernel/tests/test_e2e.py`,
  run a cell with two results through the installed kernelspec and count exactly two display
  messages, each with `text/latex` and `text/plain` in one bundle; a duplicated batch displays
  once; a failed cell displays nothing; no backend, routing or timing text appears. Repair
  `cas_display.py`, `rendering.py` or `handlers.py` where a test fails.
  **Files**: `nbdsl_kernel/tests/test_e2e.py`, `nbdsl_kernel/tests/test_cas_display.py`,
  `nbdsl_kernel/nbdsl_kernel/cas_display.py`, `nbdsl_kernel/nbdsl_kernel/rendering.py`,
  `nbdsl_kernel/nbdsl_kernel/handlers.py`.
  **Check**: `just test` (tier 2; it runs `test_e2e.py` through the installed kernelspec) and
  `uv run --project nbdsl_kernel pytest nbdsl_kernel/tests/test_cas_display.py`.
  **Acceptance**: User Story 6 scenarios 1 to 4 pass in tier 2 and the deduplication test passes
  in tier 1. **Supplies**: K:T099, which runs these display tests with the CAS batch of K:T092.
  **Inputs**: T009.

## Phase 8: Cross-cutting

- [ ] T011 Write the application logs (FR-014; research R5). Add `--log-file` to the worker
  arguments in `worker/Worker.lean` and write one record per request; write the client records in
  `worker/client.py`; pass the paths from `kernel.py` and `install.py`. Add a tier-1 test that
  runs connected cells and reads both logs.
  **Files**: `worker/Worker.lean`, `nbdsl_kernel/nbdsl_kernel/worker/client.py`,
  `nbdsl_kernel/nbdsl_kernel/kernel.py`, `nbdsl_kernel/nbdsl_kernel/install.py`,
  `nbdsl_kernel/tests/test_application_log.py` (new).
  **Check**: `uv run --project nbdsl_kernel pytest nbdsl_kernel/tests/test_application_log.py`.
  **Acceptance**: for each request the logs hold every field of research R5; the notebook shows
  none of it. **Supplies**: K FR-043, the worker part of the application log (its kernel part is
  the session log of lean-cas-dsl T127). **Inputs**: T010.
- [ ] T012 [US1] [US4] Qualify against a real `KernelSession` (FR-023). Pin
  `scripts/qualify_consumer.sh` to the lean-cas-dsl revision of research R9 (the head of the
  kernel-source branch with this repository's toolchain and K:T038, K:T085, K:T086 and K:T090
  checked), write its hash into the script and the commit body, make the script refuse another
  revision, and replace the `sage -python` start; run the qualification job of
  `.github/workflows/ci.yml` in the research image and delete its Sage 10.7 micromamba step; add a
  qualification notebook in `conformance/` with CAS cells: a retained value used in a later cell
  with one dispatch in the application log; a missing parent that is `unavailable` and runs
  nothing; a forced owner whose dependent use is unavailable; inspection with zero dispatches.
  Update `conformance/README.md` and the `casdsl` row of `conformance/test_semantic.py`.
  **Files**: `scripts/qualify_consumer.sh`, `.github/workflows/ci.yml`, the qualification notebook
  of `conformance/` (new), `conformance/README.md`, `conformance/test_semantic.py`.
  **Check**: `scripts/qualify_consumer.sh <pinned revision>` (tier 3) passes; the script exits
  nonzero on a revision with another toolchain or with one of K:T038, K:T085, K:T086 and K:T090
  unchecked.
  **Acceptance**: tier 3 passes on the pinned revision. **Consumes**: K:T038, the public entrance;
  K:T085, K:T086 and K:T090, the notebook-session source of execution, inspection and
  invalidation (research R9). **Supplies**: the notebook path of the notebook checkpoint N1
  (K:T093); the notebook-launch part of K:T153. **Inputs**: T004, T011; K:T038, K:T085, K:T086
  and K:T090, done first in lean-cas-dsl.
- [ ] T013 Bring the documents into agreement with protocol 2 (FR-021): `docs/protocol.md` (the
  frames of `contracts/wire-protocol-2.md`), `docs/architecture.md`, `docs/plugins.md` (remove
  the replayability law at `:34` and the `unsupported` seam), `README.md` (limits and verify
  section), `jupyterlab_nbdsl/README.md` (the word lists follow the lean-cas-dsl reader of
  `CasCompiler/`), the `justfile` header.
  **Files**: `docs/protocol.md`, `docs/architecture.md`, `docs/plugins.md`, `README.md`,
  `jupyterlab_nbdsl/README.md`, `justfile`.
  **Check**: `grep -rn -i -E 'replay|session[ _]cache|protocol 1|unsupported|restart' README.md
  docs/ jupyterlab_nbdsl/README.md justfile` shows no sentence that gives replay, a session cache,
  protocol 1 or an implicit restart as behaviour of this repository.
  **Acceptance**: the documents describe protocol 2 only. **Supplies**: none. **Inputs**: T011.
- [ ] T014 Release 2.0.0 (FR-022). Set `release.version = "2.0.0"` in `release.toml`, run
  `scripts/release_projection.py`, tag `v2.0.0` on `main`.
  **Files**: `release.toml`, the files that `scripts/release_projection.py` writes.
  **Check**: `gh release view v2.0.0 --repo dzackgarza/lean-jupyter-kernel` shows the release
  that the release workflow published, at a commit of `main`.
  **Acceptance**: the release workflow publishes `v2.0.0`. **Supplies**: the immutable pin that
  lean-cas-dsl locks for `nbdsl-worker` (K:T093 and issue #90). **Inputs**: T012, T013.

## Phase 9: User Story 7 - The Lean language server in Lean notebook cells (P3)

- [ ] T016 [US7] Spike the two adapters of the language-server channel (plan, "The Lean language
  server"; research R10; issue #20). Build the two-cell Mathlib-backed specimen notebook of User
  Story 7 on the `nbdsl` kernelspec in `dsl-notebooks/`, and run its steps (edit without
  execution, goal and hover in the later cell, line insertion, cell reorder, infoview suggestion,
  server restart, hidden panel) on adapter A (`jupyterlab-lsp` virtual document) and adapter B (a
  real file in `dsls/nbdsl` under `lake serve`), each with the upstream infoview in a JupyterLab
  panel. Record in research R10 the result of each step for each adapter, with its URI, project
  root, import resolution and notification flow, and the adapter that the plan's rule keeps.
  **Files**: `dsl-notebooks/lean-language-server.ipynb`, `jupyterlab_nbdsl/src/`,
  `jupyterlab_nbdsl/package.json`, `specs/001-worker-protocol-2/research.md`.
  **Check**: in JupyterLab in the research image, the steps of the specimen run on both adapters,
  and research R10 holds the result of every step for each adapter.
  **Acceptance**: research R10 names the kept adapter. **Supplies**: none. **Inputs**: T011.
- [ ] T017 [US7] Make the kept adapter the language-server channel (FR-018, FR-019): turned on per
  notebook, off on `casdsl`; the infoview host API with cursor changes, relayed notifications,
  navigation and edits mapped to cells, and the RPC session kept alive. Add
  `jupyterlab_nbdsl/ui-tests/language-server.spec.ts` (`@jupyterlab/galata`) in the research
  image: the specimen steps of User Story 7, the worker log with no request from them, and a
  `casdsl` notebook whose edits send no cell text to a language server. Document the channel in
  `docs/architecture.md` and `jupyterlab_nbdsl/README.md`.
  **Files**: `jupyterlab_nbdsl/src/`, `jupyterlab_nbdsl/package.json`,
  `jupyterlab_nbdsl/ui-tests/language-server.spec.ts` (new), `docs/architecture.md`,
  `jupyterlab_nbdsl/README.md`.
  **Check**: `just test` runs `language-server.spec.ts` through Galata in the research image.
  **Acceptance**: User Story 7 scenarios 1 to 5 pass in tier 2 (SC-010). **Supplies**: issue #20.
  **Inputs**: T016.

## Dependencies

| Task | Inputs |
| --- | --- |
| T001 | none |
| T003 | none |
| T002 | T003 |
| T004 | T002, T003; K:T352 |
| T005 | T003 |
| T015 | T005 |
| T006 | T005 |
| T007 | T005 |
| T008 | T007 |
| T009 | T008 |
| T010 | T009 |
| T011 | T010 |
| T012 | T004, T011; K:T038, K:T085, K:T086, K:T090 |
| T013 | T011 |
| T014 | T012, T013 |
| T016 | T011 |
| T017 | T016 |

T004 consumes K:T352, and T012 consumes K:T038, K:T085, K:T086 and K:T090; the workstream that
reaches T004 or T012 does those kernel tasks first (constitution, "Work order"). K:T085, K:T086 and
K:T090 close on their own checks, which use T003, T005, T006 and T008 of this list. T012 qualifies
only against a kernel at the toolchain of this repository (research R9), so it follows T004. T016
and T017 need T011 only; they follow T014 in the order.

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
| FR-017 | T015 |
| FR-018, FR-019 | T016, T017 |
| FR-020 | T001 |
| FR-021 | T013 |
| FR-022 | T014 |
| FR-023 | T012 |

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
| SC-010 | T017 |
