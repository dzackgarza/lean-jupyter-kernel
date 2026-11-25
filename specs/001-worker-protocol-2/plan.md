# Implementation Plan: Worker protocol 2 and the notebook client

**Branch**: none (work lands on `main`) | **Date**: 2026-11-25 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification `specs/001-worker-protocol-2/spec.md`

## Summary

The worker speaks protocol 2 of the notebook session contract [NS]. The client validates the
handshake before any source, executes every cell on an explicit parent, keeps queries inert,
cancels through one commit/cancel gate, reports drain and forced invalidation, publishes whole
batches once, and never restarts or replays. Most of this exists in eight local commits that
`origin` does not have. The plan lands them on `main`, closes the gaps against the
specification, aligns the toolchain with lean-cas-dsl, and adds logs, timing records and a
tier-1 commit gate. Ordinary Lean commands run in cells (FR-017). After the release that
lean-cas-dsl locks, a separate JupyterLab channel gives Lean notebook cells the Lean language
server (User Story 7, issue #20), outside the notebook unit and never on the CAS kernelspec.

## Technical Context

| Item | Value |
| --- | --- |
| Languages | Lean 4 (worker, NbDsl), Python 3 (kernel adapter, client), TypeScript (JupyterLab extension, unchanged here) |
| Lean toolchain now | `leanprover/lean4:v4.32.0` (`release.toml:14`, `worker/lean-toolchain`, `dsls/nbdsl/lean-toolchain`) |
| Lean toolchain target | `leanprover/lean4:v4.36.0-rc2`, the pin of lean-cas-dsl `main` (its `lean-toolchain`) |
| Mathlib now / target (NbDsl only) | `v4.32.0` at 81a5d25 / `master` at `5d0d3c0c77dbf2374216ade5470667f31eaa8786`, the lock of lean-cas-dsl `main` |
| Wire protocol | 1 on `main`; 2 on the local branch (`release.toml` `compat.wire_protocol`) |
| Python tooling | `uv`, strict mypy through ai-review-ci, pytest, `jupyter_client` |
| Test hosts | the shared math container `ghcr.io/dzackgarza/sage:develop` (constitution E5) |
| Tier-1 limit | 300 seconds (constitution E1) |
| Consumers | lean-cas-dsl `main` pins `nbdsl-worker` f3e73ed; the kernel branch `integration/kernel-v1-20261106` locks fb03325, a commit of the local branch |

## Constitution Check

| Article | Plan element | State |
| --- | --- | --- |
| J1 verbatim cells | No Python parsing is added; `cas_display.py` reads retained MIME data only; the language-server channel answers in the editor and never through a kernel request (FR-019) | Pass |
| J2 plugin boundary | CAS state stays in the plugin; the worker exposes `Worker.Cell.Plugin` only | Pass |
| J3 retained results | Explicit `parent_snapshot` on every execute (R1, R4) | Pass after T005 |
| J4 no replay | `cache.py`, `SessionCache.lean` removed on the branch; `restart_and_replay` removed by T009 | Pass after T009 |
| J5 inert inspection | `Query.lean` data-only on the branch; error paths checked by T006; the channel of US7 is off on `casdsl` and sends nothing to the worker (FR-019) | Pass after T006 |
| J6 handshake | `errors.py` validates `ready` on the branch | Pass after T003 |
| J7 display once | `cas_display.py` and `rendering.py` on the branch; T010 | Pass after T010 |
| J8 typed wire | `protocol.py` typed models; roundtrip codec stays independent | Pass |
| J9 toolchain | T004 | Pass after T004 |
| E1, E4 tiers and cadence | T002 | Pass after T002 |
| E3 lessons | T001 | Pass after T001 |
| E6, E7 logs and timing | T002 (test runs), T011 (application log) | Pass after T011 |

## Requirement to file map

| Requirement | Files that change | Branch state | Gap closed by |
| --- | --- | --- | --- |
| FR-001 startup | `worker/Worker/Protocol.lean`, `worker/Worker.lean` (`main`, `negotiate`) | Implemented (e27cc82, c914cd1) | T003 lands it |
| FR-002 handshake before source | `nbdsl_kernel/nbdsl_kernel/worker/client.py` (`start`), `worker/errors.py`, `protocol.py` | Implemented (fc043aa, e27cc82) | T003 |
| FR-003 header, ID admission | `worker/Worker.lean` (`handle`, `protocolError`, the claimed-ID set), `worker/requests.py` | Implemented | T003; T007 tests identical, changed and cross-operation repeats |
| FR-004 explicit parent | `worker/Worker.lean` (`execute`, `failedExecution`), `kernel.py` (`_execute_once`), `worker/client.py` (`execute`, `execute_at`) | Partial: a missing parent replies `status:"error"` with `stratum:"unavailable"`; `kernel.py` has a path that calls `execute` without a parent | T005 |
| FR-005 data-only queries | `worker/Worker/Query.lean`, `worker/Worker.lean` (`query`) | Implemented (a2e9d7d) | T006 checks the error paths and unknown modes |
| FR-006 query guards | `worker/client.py`, `handlers.py`, `kernel.py` (`do_inspect`, `do_complete`, `do_is_complete`) | Implemented for `is_complete`; not established for inspect and complete with no worker | T006 |
| FR-007 cancel gate | `worker/Worker.lean` (`cancel`, the gate), `worker/requests.py` | Implemented | T003; T007 tests queued and committed-first cancellation |
| FR-008 drain report | `worker/Worker/Cell.lean` (`Active`), `worker/Worker.lean` (`commitStatus`, `cancel`), `protocol.py` | Missing: `Active.draining` is a `Bool`; no report reaches the wire | T008 |
| FR-009 force and invalidation | `worker/Worker.lean` (`cancel` force branch), `worker/Worker/Cell.lean` (`Active.force`) | Implemented on the worker side; owner rules are lean-cas-dsl T090 | T008 tests through the native plugin |
| FR-010 committed status | `worker/Worker.lean` (`commitStatus`) | Implemented without the drain report | T008 |
| FR-011 atomic publication | `worker/Worker.lean` (`execute` commit gate), `worker/Worker/Frontend.lean`, `worker/Worker/Output.lean` | Implemented (fa2fbb7) | T003 |
| FR-012 no restart or replay | `worker/client.py` (`restart_and_replay`, `restart_fresh`), `kernel.py`, `nbdsl_kernel/tests/test_restart.py` | Partial: `restart_and_replay` remains as a raising method | T009 |
| FR-013 display once | `nbdsl_kernel/nbdsl_kernel/cas_display.py`, `rendering.py`, `handlers.py` | Implemented (23e0728, c914cd1) | T010 tests the one-emission rule end to end |
| FR-014 logs, timing | `nbdsl_kernel/tests/conftest.py` (new), `nbdsl_kernel/tests/roundtrip.py`, `worker/Worker.lean`, `worker/client.py`, `records/` (new) | Missing | T002, T011 |
| FR-015 toolchain | `release.toml`, `worker/lean-toolchain`, `dsls/nbdsl/lean-toolchain`, `dsls/nbdsl/lakefile.lean`, both `lake-manifest.json`, `worker/` sources that the toolchain change breaks | Missing | T004 |
| FR-016 tier-1 gate | `justfile` (`test-commit`, `test-push`, a new `test-tier1`), `docs/development.md` | Missing | T002 |
| FR-017 Lean commands in cells | `worker/Worker/Frontend.lean`, `worker/Worker.lean` (`execute`), `worker/Worker/NativeSession.lean` | Not established | T015 |
| FR-018, FR-019 language-server channel | `jupyterlab_nbdsl/src/` (a new channel module and the infoview panel), `jupyterlab_nbdsl/package.json`, `jupyterlab_nbdsl/ui-tests/` (new) | Missing | T016, T017 |

## Disagreements with [NS]

[NS] governs; each row names the edit and the task that makes it.

| ID | Source now | [NS] | Edit | Task |
| --- | --- | --- | --- | --- |
| N1 | `execute` on a missing parent replies `status:"error"` with `stratum:"unavailable"` (`worker/Worker.lean`, `failedExecution`) | §3.1, §5: `unavailable/snapshot_unavailable`, no prefix execution | Reply research R1 | T005 |
| N2 | `kernel.py` has a path that calls `execute` without a parent | §1, §3.1: every execution names its committed parent | Remove `execute` without a parent; compute the parent of research R4 | T005 |
| N3 | An unknown operation receives the protocol-1 `unsupported` reply (`docs/protocol.md:30-31` on `main`) | §2, §3.2: unknown operations, modes and control fields are protocol errors | Reply research R2 | T006 |
| N4 | `inspect` and `complete` with no worker are not established as `unavailable/worker_absent` | §2: no live worker gives `unavailable/worker_absent` without startup | Guards in `kernel.py` and `handlers.py` | T006 |
| N5 | `Active.draining` is a `Bool`; no drain report reaches the wire | §3.3: a cancelled cell drains its exact frames and reports a draining state | `drainReport` in the cell status (research R3) | T008 |
| N6 | `restart_and_replay` remains in `worker/client.py` as a raising method | §1, §3.1: no restart and replay, no `restart_and_replay` | Delete it and its callers | T009 |
| N7 | `docs/plugins.md:34` states a replayability law and the `unsupported` seam | §1: worker loss never authorizes replay | Rewrite the documents | T013 |
| N8 | [NS] §2 shows `"lean":"4.33.0"` in the `ready` example | §2: release and PID are diagnostic | `lean` is the `Lean.versionString` of the build (`contracts/wire-protocol-2.md`); the example is not a pin, and lean-cas-dsl T105 updates it | T003 |

## The eight local protocol-2 commits

They are on the local branch `integration/kernel-v1-20261106` of the worktree
`~/.local/share/docker/volumes/sage-repos/_data/v1-integration-20261106/lean-jupyter-kernel`
(head c914cd1). Their base is eface41; `origin/main` (819849d) has one commit that the branch
lacks: 819849d "fix: elaborate trivia-only notebook cells as no-ops (#21)", which changes
`worker/Worker/Frontend.lean`, `nbdsl_kernel/tests/roundtrip.py`, `justfile` and
`.github/workflows/ci.yml`.

| Commit | Content |
| --- | --- |
| fc043aa | `test_identity.py`: a client must refuse source paths before negotiation |
| e27cc82 | Protocol 2: `ready` with nonce, features and profile; `hello`; header and ID admission; explicit-parent execute; cancel and commit gate; `Worker/Cell.lean` plugin interface; client handshake validation |
| fa2fbb7 | Whole-batch publication through the owning transaction (`Frontend.lean`, `Cell.lean`) |
| a2e9d7d | Data-only `Query.lean`; removal of `cache.py` and `SessionCache.lean`; `requests.py` control layer; `test_native_v2.py`, `test_request_controls.py`; rewritten `docs/protocol.md`, `docs/architecture.md`, `docs/plugins.md`, `README.md` |
| 6d4cc05 | `Cell` and `Output` interfaces exposed as Lean modules for plugins |
| 23e0728 | `cas_display.py`: display of committed observations with no query execution |
| fb03325 | `test_native_v2.py`: raw-wire deadline independent of Lake discovery. lean-cas-dsl's kernel branch locks this commit |
| c914cd1 | `Worker/NativeSession.lean` (the mathlib-free native plugin), transaction ownership, observation validation, `test_native_session.py` |

Landing (T003): merge `origin/main` into the branch with a forward merge commit, resolve the
conflicts in favour of protocol 2 and of the constitution, run tier 1 and tier 2, and push the
result to `main` as a fast-forward. No commit is rewritten, so fb03325 becomes reachable from
`main` and the kernel lock resolves on GitHub.

## Toolchain alignment

| Component | Now | Target | Source of target |
| --- | --- | --- | --- |
| Lean | v4.32.0 | v4.36.0-rc2 | lean-cas-dsl `lean-toolchain` on `main` |
| Mathlib (NbDsl) | v4.32.0, 81a5d25 | `master`, 5d0d3c0 | lean-cas-dsl `lake-manifest.json` on `main` |
| Contract example | `"lean":"4.33.0"` in [NS] §2 | the value of `Lean.versionString` of the build | the worker reports its build; the example is not a pin |

T004 aligns them after T003 and after lean-cas-dsl T105, which ports the kernel branch to the same
pins (issue #90), so the worker and the kernel change toolchain together. lean-cas-dsl T093 then
locks the worker release of T014.

## Tests

| Story | Test | Tier | Path |
| --- | --- | --- | --- |
| US1 | connected cells on explicit parents; missing parent; failed cell | 1 | `nbdsl_kernel/tests/test_native_v2.py` through the production client and the native mathlib-free worker |
| US1 | the same through the installed kernelspec and a real notebook | 2 | `nbdsl_kernel/tests/test_e2e.py` |
| US1 | CAS cells with `KernelSession`: a later cell reuses a retained value with no second dispatch in the application log | 3 | `scripts/qualify_consumer.sh` against lean-cas-dsl |
| US2 | inert inspect, complete, is_complete; absent and incompatible worker; zero source bytes | 1 | `test_request_controls.py`, `test_identity.py`, `test_inspect.py` |
| US3 | cooperative, queued and already-committed cancellation; drain report | 1 | `test_request_controls.py`, `test_native_session.py` |
| US4 | force with invalidated owners; stale use unavailable | 1 and 3 | `test_native_session.py`; qualification for CAS owners |
| US5 | restart with a fresh nonce and no replay; lost reply | 1 | `test_restart.py` |
| US6 | one display event per result; no diagnostics | 1 and 2 | `test_cas_display.py`; `test_e2e.py` |
| all | protocol frames, independent codec | 1 | `nbdsl_kernel/tests/roundtrip.py` |
| US1 | an ordinary Lean command in a cell and its later use | 1 | `test_native_v2.py` |
| US7 | the two-cell specimen through JupyterLab: goal, hover, diagnostics, insertion, reorder, restart, hidden panel; no worker request; no text from `casdsl` | 2 | `jupyterlab_nbdsl/ui-tests/language-server.spec.ts` (`@jupyterlab/galata`) |

The native session plugin (`Worker/NativeSession.lean`, `Init` prelude) is the language of tier 1
where the CAS is not needed. Tier 3 uses a real `KernelSession` of lean-cas-dsl.

## The Lean language server (User Story 7)

Decision (research R10): the language server of issue #20 serves the Lean cells of the `nbdsl`
kernelspec and of the native session through a JupyterLab channel and the upstream infoview. It
is not part of the notebook unit of lean-cas-dsl, and its tasks T016 and T017 follow the release
T014 that lean-cas-dsl locks. On `casdsl` the channel is off (FR-019).

T016 is the spike: it runs the separating specimen of User Story 7 on two adapters and keeps the
one that passes every step. Adapter A is the `jupyterlab-lsp` virtual document with the Lean
server, with the kernel `language_info.file_extension` and MIME type that it requires. Adapter B
writes the language-server document as a real file inside `dsls/nbdsl` and drives `lake serve` on
it. When both pass, adapter A is kept: it reuses a maintained client and needs no file
synchronization. When neither passes, T016 records the failed step of each with the URI, project
root, import resolution and notification flow, and T017 repairs the adapter whose failure is
narrower. T017 makes the kept adapter the channel of FR-018 and FR-019.

## Project Structure

### Documentation (this feature)

```text
specs/001-worker-protocol-2/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/wire-protocol-2.md
├── checklists/requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
worker/                     Lake package nbdsl-worker (protocol, cells, queries, native plugin)
dsls/nbdsl/                 reference plugin NbDsl; Lean project of the language-server channel
jupyterlab_nbdsl/           JupyterLab extension: highlighting; the language-server channel (US7)
nbdsl_kernel/nbdsl_kernel/  ipykernel adapter, client, display
nbdsl_kernel/tests/         tier-1 and tier-2 suites
scripts/                    check and consumer qualification
records/                    test-run logs and timing records (new)
```

## Complexity Tracking

No article is violated.
