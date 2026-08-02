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

Root `pyproject.toml` is a uv workspace marker; `AGENTS.md` is agent-tooling
registration (owned by that tooling, not by hand).

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

Worker-heavy checks use the shared `NBDSL_CONFORMANCE_LOCK` and export
`LEAN_NUM_THREADS=1`. Serialize heavy jobs rather than overlapping them with
`scripts/check.sh` or consumer qualification. On constrained machines, an
optional local `systemd-run` boundary is fine; resource policy is not a
package subsystem.

## Test suites — what proves what

| Suite | Runs | Proves |
| --- | --- | --- |
| `nbdsl_kernel/tests/roundtrip.py` | bare worker, raw JSON (stdlib only) | the wire protocol itself: framing, atomicity/rollback (incl. registry state), cross-cell scope state, Unicode columns, stdout isolation, multi-command message/sorry accumulation, sorries, DSL sequence + structured output, predicates, is_complete, completion (prefix + dot), hover, cooperative cancel timing, clean shutdown. **Independent oracle: keep its codec duplicated, never import the client's.** |
| `nbdsl_kernel/tests/test_e2e.py` | installed kernelspec via jupyter_client | the full stack: eval/state, failure isolation, DSL output through Jupyter, complete/inspect requests, interrupt → cache restore (and registry surviving the olean round-trip), uncacheable-state → replay fallback, init cell (success and loud failure), document-order semantics incl. the staleness broadcast, driven by raw comm messages exactly as JupyterLab sends them |
| `nbdsl_kernel/tests/test_clean_install.py` | built adapter wheel in a fresh venv | Journey 1: install kernelspec against in-repo `dsls/nbdsl`, run Lean + NbDsl cells, confirm the live worker exe is the project's built binary |
| `conformance/test_semantic.py` | installed `nbdsl` / `casdsl` kernelspecs | NbDsl: rollback, cancel, output transport, Lean queries, recovery. lean-cas-dsl: extension visibility, rich MIME, recovery, Sage assert (checkout owned by qualification via `CONFORMANCE_CAS_DSL`) |
| `nbdsl_kernel/tests/test_identity.py` | bare worker | wire-protocol gate: `check_wire_protocol` refuses a mismatched `ready.protocol`; a live worker must speak `WIRE_PROTOCOL` |
| `nbdsl_kernel/tests/test_restart.py` | production WorkerClient + live kernelspec, mathlib-free (`Init` prelude) | recovery laws: failed mid-replay must not consume the ledger; cache restore then kill again must recover; worker death restarts transparently; external-effect + death does not re-run the cell |
| `nbdsl_kernel/tests/test_inspect.py` | production WorkerClient, mathlib-free (`Lean` prelude) | inspection discriminates under a plugin catch-all: a low-priority bare-`term` command used to make every `inspect` answer with that syntax declaration's docstring, shadowing real constants. Reproduced in plain Lean, no plugin needed |
| `nbdsl_kernel/tests/sandbox_check.py` | production WorkerClient under bwrap | optional local sandbox proof (not a PR blocking gate; issue #1 lists hostile-notebook sandbox certification as a non-goal) |
| `jupyterlab_nbdsl/` `jlpm test` | node, no browser | tokenizer (incl. `:=`, unicode, custom keywords), document message builder, stale-class computation, path-payload validation |
| `scripts/check.sh` | build + roundtrip + e2e | local verification without the optional sandbox proof |

The Journey 1 test installs the adapter wheel against the already-built
in-repo `dsls/nbdsl` project. Nested Git/Lake consumer resolution is covered
by `test_worker_resolve.py` and real `lean-cas-dsl` qualification.

Test-harness lore paid for in debugging time: match Jupyter replies by
`parent_header.msg_id` in a loop (never assert on "the next reply" — stale
replies race), and remember several e2e tests are order-dependent on the
module-scoped kernel (document-mode recovery differs from REPL, so the
interrupt test must precede the document test).

## CI (`.github/workflows/ci.yml`)

Four jobs on push/PR: `worker` (mathlib-free build + boundary grep),
`dsl` (mathlib cache → builds → in-repo mypy.ini → roundtrip → E2E,
Journey 1, recovery, NbDsl semantic journeys), `compat` (release projection
plus frozen-consumer qualification with concrete Sage/Jupyter gates), and
`frontend` (jlpm install/test + clean wheel install/activation).

## Ceilings & parked work (deliberate, not forgotten)

- Snapshots are never garbage-collected; memory grows with committed cells.
- Prefix completion is an environment scan (dot completion is type-aware);
  full expected-type-aware completion would use `Lean.Server.Completion`.
- The session cache refuses open scopes / `variable` decls /
  syntax-valued options (falls back to replay) and is validated by the ledger
  key plus the selected module/scope hashes and load success, not by replay
  comparison.
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
- The owned child is `nbdsl_worker` itself (after capturing `lake env`); kill the process group, not a wrapper pid.
