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
tier-1 commit gate.

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
| J1 verbatim cells | No Python parsing is added; `cas_display.py` reads retained MIME data only | Pass |
| J2 plugin boundary | CAS state stays in the plugin; the worker exposes `Worker.Cell.Plugin` only | Pass |
| J3 retained results | Explicit `parent_snapshot` on every execute (R1, R4) | Pass after T005 |
| J4 no replay | `cache.py`, `SessionCache.lean` removed on the branch; `restart_and_replay` removed by T009 | Pass after T009 |
| J5 inert inspection | `Query.lean` data-only on the branch; error paths checked by T006 | Pass after T006 |
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

T004 aligns them after T003. lean-cas-dsl issue #90 ports the kernel branch to the same pins and
then locks the aligned worker revision.

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

The native session plugin (`Worker/NativeSession.lean`, `Init` prelude) is the language of tier 1
where the CAS is not needed. Tier 3 uses a real `KernelSession` of lean-cas-dsl.

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
dsls/nbdsl/                 reference plugin NbDsl
nbdsl_kernel/nbdsl_kernel/  ipykernel adapter, client, display
nbdsl_kernel/tests/         tier-1 and tier-2 suites
scripts/                    check and consumer qualification
records/                    test-run logs and timing records (new)
```

## Complexity Tracking

No article is violated.
