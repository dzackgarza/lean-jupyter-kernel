# lean-jupyter-kernel

Proof of concept: **a Lean 4 elaborated DSL running as a first-class Jupyter
kernel.** Lean owns syntax, elaboration, semantic state, and proof checking;
Jupyter owns transport and rendering. Cells reach Lean verbatim — no DSL
logic exists in Python.

```text
JupyterLab / jupyter console
        │  Jupyter kernel protocol (ZMQ)
        ▼
nbdsl_kernel        Python, ipykernel wrapper kernel (thin adapter)
        │  length-prefixed JSON frames on dedicated inherited fds
        ▼
nbdsl_worker        Lean executable, started under `lake env`
        │  persistent Command.State snapshots, one per committed cell
        ▼
NbDsl               the DSL: command elaborators, persistent registry,
                    Mathlib-backed categories, structured MIME outputs
```

## Layout

- `worker/` — Lake package `nbdsl-worker`, the notebook core: framed
  protocol, per-cell elaboration, snapshot DAG, cancellation, query services,
  and the `Worker.Output` sink. Mathlib-free (builds in seconds); the stable
  dependency surface for DSL plugins.
- `dsls/nbdsl/` — the reference DSL plugin: a Lake package (`require`s the
  worker by path, mathlib `v4.32.0`):
  - `NbDsl/Basic.lean` — `LargeCat`/`Object` over Mathlib `Cat`; `Object` is a
    transparent `def` so home categories are recovered by head-symbol matching.
  - `NbDsl/Registry.lean` — preferred-functor registry as a
    `SimplePersistentEnvExtension`: semantic state lives in the `Environment`,
    so it snapshots, rolls back, and replays with cells.
  - `NbDsl/Syntax.lean` — `let X := t ∈ C` (elaborates to a kernel-checked
    `noncomputable def X : Object C := t`), `prefer F`, `#home X`, `#via X ∈ C`.
  - `NbDsl/Std.lean` — `Sets`, `Groups`, forgetful functor.
  - `NbDsl/Notebook.lean` — the prelude module (the plugin's entry point).
- `nbdsl_kernel/` — Python package: `kernel.py` (ipykernel subclass),
  `worker.py` (spawn/framing/replay ledger), `install.py` (kernelspec),
  `tests/roundtrip.py` (protocol spec by example), `tests/test_e2e.py`
  (Jupyter-level invariants).
- `notebooks/demo.ipynb` — the acceptance demo.

## Quickstart

```bash
just cache && just build
uv venv .venv && uv pip install -p .venv/bin/python -e 'nbdsl_kernel[test]'
.venv/bin/python -m nbdsl_kernel.install --project "$PWD/dsls/nbdsl"
jupyter lab notebooks/demo.ipynb   # kernel: "NbDsl (Lean 4)"
```

`scripts/check.sh` runs the full gate: build → no-sorry QC → worker protocol
roundtrip → Jupyter E2E.

## Semantics

- **Cell atomicity.** A cell (possibly several commands) elaborates against a
  copy of the parent `Command.State`; the candidate state is committed as a
  new snapshot only if no diagnostic has error severity. A failed cell leaves
  committed state — including registry entries — identical to its parent.
- **Full state, not just the environment.** Snapshots retain the complete
  `Command.State`: namespaces/sections, `open`s, options, macro-scope
  counters, name generators. `set_option` and a dangling `namespace` survive
  cell boundaries; the end-of-input token is never elaborated, so open scopes
  don't error.
- **Protocol isolation.** Control frames travel on dedicated fds; user output
  cannot forge a frame (`#eval` prints are additionally captured by Lean into
  the message log and surface as info diagnostics).
- **Interrupt = cooperative cancel, then kill + replay.** The worker runs in
  its own session; Jupyter's interrupt reaches only the kernel, which sends a
  `cancel` frame. A reader task sets the in-flight `IO.CancelToken`, and
  elaboration aborts at its next checkpoint (~0.2s for tactic proofs — the
  same mechanism the language server uses) with `status:"cancelled"` and no
  commit. Code that never reaches a checkpoint (e.g. an interpreted `#eval`
  loop) is escalated after a grace window: the worker is killed and the next
  execute restarts it and replays the committed cell ledger — source replay
  is the canonical record (scoped environment state does not pickle reliably).
- **Document order, not execution order.** With the `jupyterlab_nbdsl`
  extension, the frontend streams the notebook's code-cell order and sources
  over the `nbdsl_document` comm. Running a cell first re-establishes the
  invariant *"the snapshot for cell i is exactly the state of elaborating the
  visible prefix through cell i"*: unchanged prefix cells reuse their cached
  snapshots (the worker's snapshot DAG), edited or moved ones re-run
  automatically (`↻ re-running upstream cell k…`), and an upstream failure
  aborts the run with that cell's error. Without the comm (jupyter console),
  execution keeps plain REPL semantics.
- **Positions.** Diagnostic columns are Unicode code points end to end
  (Lean's `FileMap.toPosition` ↔ Jupyter's `cursor_pos`); no byte/codepoint
  conversion exists anywhere.

## Protocol (spec by example: `nbdsl_kernel/tests/roundtrip.py`)

Ops: `execute {request_id, parent_snapshot, cell_id, code}` →
`{status: ok|error|cancelled, snapshot, diagnostics, sorries, outputs}`;
`is_complete {code}` → `{result: complete|incomplete|invalid}` (parse-only,
Lean's parser decides — powers `do_is_complete`); `complete {code, cursor}` →
`{matches, cursor_start, cursor_end}` (identifier-prefix completion against
the snapshot environment, aware of the current namespace and `open`s; cursor
offsets are code points); `inspect {code, cursor}` → `{found, name, type,
doc}` (resolution the way a cell would resolve, type via the pretty printer,
docstring included); `cancel {request_id}` (out-of-band, no reply of its own
— the cancelled execute replies); `describe`. Unknown ops answer
`{"status": "unsupported"}`.

## Bring your own DSL

The notebook core is DSL-agnostic, and the boundary is enforced (the QC gate
fails if `Worker.*` ever imports a DSL module). A custom or replacement DSL
is:

1. a Lean package (or extra modules here) whose elaborators may `import
   Worker.Output` and call `Worker.emitOutput` for rich MIME outputs — the
   dependency arrow is always DSL → Worker;
2. a prelude module importing your DSL surface;
3. a kernelspec: `python -m nbdsl_kernel.install --project <your project>
   --prelude-module Your.Prelude --name yourdsl`.

Nothing in the worker, Python kernel, or Lab extension changes. `dsls/nbdsl`
is the reference plugin: `require «nbdsl-worker» from …` (path or git),
build `nbdsl_worker` once, done — the kernel resolves the binary from the
project's build tree, a git dependency's, or a path dependency's (read from
the Lake manifest). One cosmetic seam: `prefer` is hardcoded as a keyword in
the highlighter; new `#commands` highlight automatically.

## Milestone 2 remaining (seams left)

JupyterLab extension for cell-order tracking, virtual-document source maps
with prefix invalidation, InfoTree-backed (expected-type-aware) completion
and hover to replace the environment-scan versions, snapshot pickling as a
validated cache, OS-level sandboxing for untrusted notebooks.
