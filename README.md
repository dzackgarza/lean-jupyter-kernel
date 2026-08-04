# lean-jupyter-kernel

A Jupyter kernel that runs Lean 4 cells against a persistent worker process.
Cells are ordinary Lean — the kernel never interprets DSL syntax.
Completion, hover, diagnostics, and document-order semantics are asked of the
Lean worker, not computed in Python.

**Document-order semantics is a deliberate philosophy, not an accident.**
In this kernel the notebook is a document, not a transcript: cell *i*'s
state is always the state of elaborating the *visible* prefix of the
notebook through cell *i*. Outputs therefore always correspond to the
source shown above them. Standard notebooks let a cell's output silently
diverge from the visible source — the classic stale-state footgun, where
cell 5's result was computed against a version of cell 2 that no longer
exists on screen. That divergence is the failure mode this kernel exists
to exclude. Unchanged prefix cells reuse cached snapshots (editing cell 2
does not re-run cell 1); edited or moved cells re-run (shown with `↻`
notes); an upstream failure aborts with `UpstreamError` rather than
leaving the notebook in an unknown, inconsistent state.

The plain execution-order REPL model remains available — in `jupyter
console`, or in any client that does not stream the document comm —
where each cell appends to the current context and `let` re-binding
shadows, exactly as in a standard notebook kernel. The two modes share
the same worker, the same snapshot DAG, and the same atomicity: a cell
commits only if it elaborates with no error-severity diagnostic.

Consumed by:

- [lean-cas-dsl](https://github.com/dzackgarza/lean-cas-dsl) — a
  categorically organized computer algebra system
- [lean-lattices](https://github.com/dzackgarza/lean-lattices) — checked
  categories, structural functors, and operation graphs

## Install

Requires [elan](https://github.com/leanprover/elan), `uv`, and `just`.

```bash
just cache && just build
uv venv .venv && uv pip install -p .venv/bin/python -e 'nbdsl_kernel[test]' -e jupyterlab_nbdsl
.venv/bin/python -m nbdsl_kernel.install --project "$PWD/dsls/nbdsl"
PATH="$PWD/.venv/bin:$PATH" .venv/bin/jupyter labextension develop --overwrite jupyterlab_nbdsl
```

## Usage

```bash
jupyter lab dsl-notebooks/nbdsl-example.ipynb   # kernel: "NbDsl (Lean 4)"
```

The notebook demonstrates the reference DSL: checked categorical membership
(`let S3 := GrpCat.of (Equiv.Perm (Fin 3)) ∈ Groups`), transport conventions
(`prefer`), functor-path search (`#via`), and document-order cell semantics.

## Docs

| Doc | Contents |
| --- | --- |
| [docs/architecture.md](docs/architecture.md) | processes, worker internals, kernel modes, recovery, plugins |
| [docs/protocol.md](docs/protocol.md) | wire protocol: framing, ops, reply shapes |
| [docs/dsl.md](docs/dsl.md) | NbDsl language reference |
| [docs/plugins.md](docs/plugins.md) | plugin contract, laws, kernelspec knobs |
| [docs/deployment.md](docs/deployment.md) | install into a live Jupyter service |
| [docs/development.md](docs/development.md) | layout, gates, test suites, CI, ceilings |

## Verify

```bash
scripts/check.sh
```

Runs build, no-sorry scan, mypy, protocol roundtrip, Jupyter E2E, and sandbox
proof.

## Limits

- Cells are trusted — no sandbox certification for hostile notebooks (opt-in
  bubblewrap available).
- Snapshot memory grows with committed cells (no GC).
- Plugin query contract for extension-backed completion/inspection is future
  work.

## License

MIT
