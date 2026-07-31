# Development

## Layout

| Path | What | Owner of |
| --- | --- | --- |
| `worker/` | Lake package `«nbdsl-worker»` (mathlib-free core) | protocol, elaboration, snapshots, cancellation, cache, query services, output sink |
| `dsls/nbdsl/` | Lake package `nbdsl` (reference DSL plugin) | `NbDsl.*`, the `NbDsl.Notebook` prelude |
| `nbdsl_kernel/` | Python package | ipykernel adapter, worker client, typed protocol models, kernelspec installer, test suites |
| `jupyterlab_nbdsl/` | JupyterLab 4 federated extension | highlighting, document/staleness comm, path renderer |
| `dsl-notebooks/` | notebooks (symlinked into the live notebooks tree) | the pedagogical example |
| `docs/` | this documentation | — |

Root `pyproject.toml` is a uv workspace marker; `AGENTS.md`/`SDL.md` are
agent-tooling registration (owned by that tooling, not by hand).

## Build & gates

```bash
just cache        # mathlib prebuilt oleans (dsls/nbdsl)
just build        # worker exe (seconds) + NbDsl (fast once cache is in)
just test         # the full commit gate, see below
```

`just test` = both builds → Lean no-sorry scan over both packages → the
**boundary grep** (`import NbDsl` under `worker/` fails the build) → the
global ai-review-ci **strict mypy** over `nbdsl_kernel` → the protocol
roundtrip. Commit and push hooks run it; don't hand-run whole suites beyond
this while iterating — targeted runs are fine.

Note the QC stanza situation: this is a polyglot monorepo and ai-review-ci's
doctor has no profile for that, so the repo declares no `ai_review_ci_*`
contract and calls the private `_mypy` recipe directly
(ai-review-ci#353 tracks the gap).

## Test suites — what proves what

| Suite | Runs | Proves |
| --- | --- | --- |
| `nbdsl_kernel/tests/roundtrip.py` | bare worker, raw JSON (stdlib only) | the wire protocol itself: framing, atomicity/rollback (incl. registry state), cross-cell scope state, Unicode columns, stdout isolation, multi-command message/sorry accumulation, sorries, DSL sequence + structured output, predicates, is_complete, completion (prefix + dot), hover, cooperative cancel timing, clean shutdown. **Independent oracle: keep its codec duplicated, never import the client's.** |
| `nbdsl_kernel/tests/test_e2e.py` | installed kernelspec via jupyter_client | the full stack: eval/state, failure isolation, DSL output through Jupyter, complete/inspect requests, interrupt → cache restore (and registry surviving the olean round-trip), uncacheable-state → replay fallback, init cell (success and loud failure), document-order semantics incl. the staleness broadcast, driven by raw comm messages exactly as JupyterLab sends them |
| `nbdsl_kernel/tests/test_identity.py` | bare worker + installed kernelspec | build identity end to end: `ready`/`describe` carry the authored `release.toml` contract plus a real commit, the `nbdsl_provenance` comm publishes the compared pair and the SHA-256 of the binary actually executed, a static contract mismatch refuses cells typed, a commit mismatch on a dirty tree runs and reports `unverifiable-dirty`, and missing build info is a typed error from a live kernel. Staged by pointing a real kernel at a scratch build-info file via `NBDSL_BUILD_INFO` — the authoritative file is never mutated |
| `nbdsl_kernel/tests/test_restart.py` | production WorkerClient, mathlib-free (`Init` prelude) | recovery laws, as red tests for two shipped defects: a failed replay must not consume the ledger (it used to truncate it, so the next restart replayed a stump and reported success over a half-empty environment), and a session restored from cache then killed again must recover (it used to abort the worker with a stack overflow — saving a restored state wrote an olean importing itself) |
| `nbdsl_kernel/tests/test_inspect.py` | production WorkerClient, mathlib-free (`Lean` prelude) | inspection discriminates under a plugin catch-all: a low-priority bare-`term` command used to make every `inspect` answer with that syntax declaration's docstring, shadowing real constants. Reproduced in plain Lean, no plugin needed |
| `nbdsl_kernel/tests/sandbox_check.py` | production WorkerClient under bwrap | read-only project, private tmpfs, elaboration alive; **fails loudly if bwrap is missing** (not in CI — runners lack reliable userns; `scripts/check.sh` covers it locally) |
| `jupyterlab_nbdsl/` `jlpm test` | node, no browser | tokenizer (incl. `:=`, unicode, custom keywords), document message builder, stale-class computation, path-payload validation |
| `scripts/check.sh` | everything above + e2e + kernelspec install | the full local verification |

Test-harness lore paid for in debugging time: match Jupyter replies by
`parent_header.msg_id` in a loop (never assert on "the next reply" — stale
replies race), and remember several e2e tests are order-dependent on the
module-scoped kernel (document-mode recovery differs from REPL, so the
interrupt test must precede the document test).

## CI (`.github/workflows/ci.yml`)

Three jobs on push/PR: `worker` (mathlib-free build + boundary grep, ~30 s),
`dsl` (mathlib cache → builds → strict mypy with ai-review-ci's config
fetched raw → roundtrip → kernelspec + e2e; ~2–4 min warm via
`actions/cache`), `frontend` (jlpm install/test/build, ~1 min).
CI green does **not** cover the sandbox claim (documented in the workflow).

## Ceilings & parked work (deliberate, not forgotten)

- Snapshots are never garbage-collected; memory grows with committed cells.
- Prefix completion is an environment scan (dot completion is type-aware);
  full expected-type-aware completion would use `Lean.Server.Completion`.
- The session cache refuses open scopes / `variable` decls /
  syntax-valued options (falls back to replay) and is validated by key
  match + load success, not by replay comparison.
- `predicate` records the object part only; the iso-invariance
  (functoriality through `core(C)`) obligation is the designed next step,
  as is a registered free-group functor making `#via B ∈ Groups` resolve.
- Mixed console+notebook sessions: document-mode recovery drops REPL
  history (document state wins).

## Debugging the worker

- The worker's stderr reaches the kernel's pump and shows as notebook
  stderr; the service journal has the kernel process's own stderr.
- Orphan hunting: `pgrep -fa nbdsl_worker`; a healthy system has exactly
  one per live kernel. Post-mortem thread states (`/proc/PID/task/*/wchan`)
  distinguish idle-blocked (futex, EOF-recoverable) from spinning
  (interpreted loop, killpg only) from IO-thrashing (`filemap_fault`,
  check disk).
- `lake env` forks: kill the process group, not the pid.
