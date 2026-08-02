# lean-jupyter-kernel

Proof of concept: **a Lean 4 elaborated DSL running as a first-class
Jupyter kernel.** Lean owns syntax, elaboration, semantic state, and proof
checking; Jupyter owns transport and rendering. Cells reach Lean verbatim —
no DSL logic exists in Python, and everything semantic (completion, hover,
completeness, staleness) is asked *of* the Lean worker, never computed
beside it.

```text
JupyterLab ──ZMQ──▶ nbdsl_kernel (Python adapter)
                        │ framed JSON on dedicated fds
                        ▼
                 nbdsl_worker (persistent Lean process)
                        │ importModules, once
                        ▼
                 DSL prelude (Lean elaborators + env extensions,
                              all of mathlib in scope)
```

## What it does

- **Cells are ordinary Lean 4** over the full mathlib (`sage.all`-style),
  elaborated against retained `Command.State` snapshots. Cells are atomic:
  an erroring cell commits nothing, including DSL registry mutations.
- **The reference DSL** makes categorical bookkeeping explicit and checked:
  `let S3 := GrpCat.of (Equiv.Perm (Fin 3)) ∈ Groups` (membership is a type
  ascription), `prefer` (transport conventions as document state), `#home`,
  `#via` (functor-path search with structured MIME output), and
  `predicate P (x ∈ C) := …` / `#methods C` (predicates as methods of a
  category, decidable on declared objects: `¬ Abelian S3 := by decide`).
- **Document-order semantics** in JupyterLab: running a cell re-establishes
  *"cell i's snapshot = elaborating the visible prefix through i"* —
  edited upstream cells re-run automatically, stale cells are marked in the
  UI.
- **Tooling from the environment**: Tab completion (type-aware after a
  dot), Shift+Tab hover (server-grade, locals included), sorry tracking
  with goals, syntax highlighting.
- **Robust interruption**: cooperative cancellation via Lean's own
  checkpoints (~0.2 s on tactic proofs), kill + recovery otherwise —
  recovery by olean session cache (env-extension state survives) or source
  replay.
- **Opt-in sandboxing** for untrusted notebooks (bubblewrap: read-only
  project/toolchain, no network).

The worked demonstration is `dsl-notebooks/nbdsl-example.ipynb` — a
pedagogical notebook proving all of the above live, including a
deliberately failing final cell.

## Quickstart

```bash
just cache && just build
uv venv .venv && uv pip install -p .venv/bin/python -e 'nbdsl_kernel[test]' -e jupyterlab_nbdsl
.venv/bin/python -m nbdsl_kernel.install --project "$PWD/dsls/nbdsl"
PATH="$PWD/.venv/bin:$PATH" .venv/bin/jupyter labextension develop --overwrite jupyterlab_nbdsl
jupyter lab dsl-notebooks/nbdsl-example.ipynb   # kernel: "NbDsl (Lean 4)"
```

`scripts/check.sh` runs the full verification (builds, no-sorry, boundary
grep, strict mypy, protocol roundtrip, Jupyter E2E, sandbox proof).

## Documentation

| Doc | Contents |
| --- | --- |
| [docs/architecture.md](docs/architecture.md) | the three processes, worker internals (snapshots, cancellation, session cache), kernel modes, recovery matrix, extension plugins |
| [docs/protocol.md](docs/protocol.md) | the wire protocol: framing, every op with reply shapes, conventions |
| [docs/dsl.md](docs/dsl.md) | the NbDsl language reference, the reducibility design, parser lore |
| [docs/plugins.md](docs/plugins.md) | bring your own DSL: the plugin contract and laws, kernelspec knobs |
| [docs/deployment.md](docs/deployment.md) | editable install into a live Jupyter service, operational characteristics |
| [docs/development.md](docs/development.md) | layout, gates, what each test suite proves, CI, deliberate ceilings |

## Layout

`worker/` (mathlib-free Lean core, the stable plugin dependency) ·
`dsls/nbdsl/` (reference DSL plugin) · `nbdsl_kernel/` (Python adapter +
suites) · `jupyterlab_nbdsl/` (Lab extension) · `dsl-notebooks/` (live
notebooks) · `docs/`.

## Status

Working POC, verified at four levels: bare-worker protocol roundtrip,
Jupyter-client E2E, live-service execution, and CI on every push. Design
ceilings are deliberate and listed in
[docs/development.md](docs/development.md#ceilings--parked-work-deliberate-not-forgotten).
