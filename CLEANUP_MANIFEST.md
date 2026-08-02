# PR #10 cleanup manifest — keep / replace / delete

**Goal:** shrink the diff to notebook product behavior and the minimum real-boundary
evidence. Journeys, certificates, and review machinery are not the product
([issue #1](https://github.com/dzackgarza/lean-jupyter-kernel/issues/1)).

**Baseline:** `92c0cae…` → pre-cleanup tip (~+10,742 / −230, 52 files).

**Target:** ~+2,500–3,500 product + evidence LOC after cleanup (~6.8–7.9k removable).

---

## Legend

| Tag | Meaning |
| --- | --- |
| **KEEP** | Product behavior or high-value regression; do not weaken |
| **REPLACE** | Keep the claim; delete the mini-platform and rewrite smaller |
| **DELETE** | Remove from the product diff in Phase 1 |
| **DECOUPLE→DELETE** | Remove only after runtime no longer depends on it (Phase 2+) |

---

## File-by-file

### Process / agent artifacts

| Path | Action | Notes |
| --- | --- | --- |
| `.pr/PR_BODY.md` | **DELETE** (Phase 1) | Process artifact; not product |
| `.pr/REVIEW_DISPOSITIONS.md` | **DELETE** (Phase 1) | Disposition ledger; not product |
| `.pr/triage_state.json` | **DELETE** (Phase 1) | Same |
| `SDL.md` | **DELETE** (Phase 1) | Agent workflow mirror; not notebook product |
| `AGENTS.md` Review Guidelines append | **DELETE** (Phase 1) | Revert to SDL bootstrap + agent-memory only |
| `CLEANUP_MANIFEST.md` (this file) | **KEEP until Phase 2 closes** | Then delete or fold into issue #1 |

### Conformance mini-platform

| Path | Action | Notes |
| --- | --- | --- |
| `conformance/runner.py` (~1422) | **REPLACE** | → ~400–600 line parametrized pytest + shared Jupyter fixture |
| `conformance/nbdsl.toml` | **REPLACE** | → small plugin case object / fixture data |
| `conformance/lean-cas-dsl.toml` | **REPLACE** | Same |
| `conformance/test_runner_contracts.py` (~463) | **REPLACE** | Most tests certify the runner, not the notebook |
| `conformance/README.md` | **REPLACE** | Document the thin pytest surface |
| `conformance/test_release_governance.py` (~745) | **DELETE** (Phase 1) | Meta-certification of projection/provenance/PR body |
| `conformance/test_resource_limits.py` (~174) | **DELETE** (Phase 1) | Tests the containment subsystem, not notebooks |

### Resource containment

| Path | Action | Notes |
| --- | --- | --- |
| `nbdsl_kernel/nbdsl_kernel/resource_limits.py` (~375) | **DELETE** (Phase 1) | Protects the heavy suite from itself |
| `scripts/resource_limited.py` | **DELETE** (Phase 1) | Wrapper only |
| `justfile` / `ci.yml` / `check.sh` / `qualify_consumer.sh` wrappers | **REPLACE** (Phase 1) | Call commands directly; `LEAN_NUM_THREADS=1` + serialize heavy jobs |

### Release / identity / provenance

| Path | Action | Notes |
| --- | --- | --- |
| `scripts/release_provenance.py` | **DELETE** (Phase 1) | Second identity object + hash theater |
| `scripts/require_release_qualification.sh` | **DELETE** (Phase 1) | Exact-check gate on evidence schema |
| `scripts/release_projection.py` | **REPLACE** | Tiny version-field sync/check at release time |
| `release.toml` | **REPLACE→KEEP thin** | Wire + package versions only; drop commit epistemology |
| `nbdsl_kernel/tests/test_identity.py` (~540) | **REPLACE** | Keep wire-protocol mismatch refusal; drop SHA/hash/comm theater |
| `nbdsl_kernel/_identity.py` | **DECOUPLE→DELETE** | After hatch/worker stop requiring it |
| `nbdsl_kernel/hatch_build.py` | **DECOUPLE→DELETE** | Standard packaging after |
| `scripts/sync_build_info.py` | **DECOUPLE→DELETE** | |
| `worker/Worker/BuildCommit.lean` | **DECOUPLE→DELETE** | |
| `worker/Worker/ReleaseInfo.lean` | **DECOUPLE→DELETE** (or thin static wire version) | |
| `nbdsl_provenance` comm (`kernel.py`, tests) | **DECOUPLE→DELETE** | |
| Executable `/proc` hashing + exact-commit compare in `WorkerClient` | **DECOUPLE→DELETE** | Also removes portability/race defect |
| `.github/workflows/release.yml` provenance / exact-check steps | **DELETE** (Phase 1) | Keep ordinary release packaging |

### Consumer qualification

| Path | Action | Notes |
| --- | --- | --- |
| `scripts/qualify_consumer.sh` (~205) | **REPLACE** | → ~60–90 lines: pin, build, Sage/Jupyter gate, small external journeys, no semantic consumer edit |

### Product runtime (KEEP — do not gut)

| Path | Action | Notes |
| --- | --- | --- |
| `nbdsl_kernel/nbdsl_kernel/kernel.py` | **KEEP** (trim provenance later) | Jupyter surface |
| `nbdsl_kernel/nbdsl_kernel/worker.py` | **KEEP** (trim identity/hash later) | Process + ledger + recovery |
| `nbdsl_kernel/nbdsl_kernel/protocol.py` | **KEEP** (trim identity types later) | Wire types |
| `worker/Worker.lean` | **KEEP** | Transactions |
| `worker/Worker/Query.lean` | **KEEP** | Plugin queries / probeExpression |
| `worker/Worker/SessionCache.lean` | **KEEP** | Cache recovery |
| `worker/Worker/Frontend.lean`, `Output.lean`, `Protocol.lean` | **KEEP** | Unchanged ownership |

### Product evidence (KEEP / thin)

| Path | Action | Notes |
| --- | --- | --- |
| `nbdsl_kernel/tests/test_restart.py` | **KEEP** high-value 4; **REPLACE** fixtures | Ledger, second recovery, wrapper death, ambiguous-death no-retry |
| `nbdsl_kernel/tests/test_inspect.py` | **KEEP** | Catch-all inspection defect |
| `nbdsl_kernel/tests/test_clean_install.py` | **REPLACE** | One clean wheel + nested Git/Lake; local-path → resolver unit |
| `nbdsl_kernel/tests/roundtrip.py` | **KEEP** | Independent codec oracle |
| `nbdsl_kernel/tests/test_roundtrip_cleanup.py` | **KEEP** | Process cleanup |
| `nbdsl_kernel/tests/test_build_artifacts.py` | **REPLACE / thin** | After identity decoupling |
| `jupyterlab_nbdsl/*` packaging alignment | **KEEP** | Distributable wheel — product |

### Docs / packaging touch-ups

| Path | Action | Notes |
| --- | --- | --- |
| `docs/development.md`, `protocol.md`, `plugins.md` | **REPLACE** | Describe thin evidence; drop provenance theology |
| `justfile`, `.github/workflows/ci.yml` | **REPLACE** (Phase 1 partial) | No resource_limited; no governance suite; keep journey pytest |
| `dsls/nbdsl/lakefile.lean`, `worker/lakefile.lean` | **KEEP** / trim BuildCommit hooks in Phase 2 | |

---

## Phased execution

### Phase 1 — deletion commit (done / in flight)

Delete process artifacts, resource-containment package, release-governance tests/scripts,
provenance exact-check script. Retarget justfile/CI/check/qualify off `resource_limited`.
Strip `require_active_resource_scope` from `conformance/runner.py` so journeys still run.
**Do not** yet remove runtime identity (would break build).

### Phase 2 — replace conformance + qualify_consumer

One pytest module, two plugin cases, thin qualify script. Preserve six user-visible
behaviors and external Sage/Jupyter gate.

### Phase 3 — decouple identity / provenance

Wire-protocol version check only. Delete `_identity`, BuildCommit, provenance comm,
`/proc` exe hashing, most of `test_identity.py`. Optionally launch `nbdsl_worker`
directly after capturing `lake env` (collapse wrapper/worker topology).

### Phase 4 — thin clean-install + shared fixtures

Shared Jupyter + process-tree helpers; keep nested Git/Lake; demote local-path.

---

## Must survive every phase

- Transactional success / error / parse-error / cancellation
- Replay-ledger preservation; repeated cache recovery
- No automatic retry after ambiguous execution death
- Plugin-aware completion and inspection
- Output vs control-frame transport separation
- One clean installed-kernelspec path (nested Git/Lake)
- One real `lean-cas-dsl` Sage/Jupyter journey
- Focused regressions for each shipped defect already found
