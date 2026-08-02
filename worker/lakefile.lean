import Lake
open Lake DSL System

/-
The notebook core: framed protocol, per-cell elaboration, snapshot DAG,
cancellation, and the output sink. Deliberately mathlib-free — it builds in
seconds and is the stable dependency surface for DSL plugin packages
(`require «nbdsl-worker» from git/path`, import `Worker.Output`, nothing
else). The QC gate rejects any `import NbDsl` under Worker sources.
-/
package «nbdsl-worker» where
  version := v!"1.1.0"

@[default_target]
lean_lib Worker

/--
The persistent notebook worker. `supportInterpreter` is required because
cells are elaborated (and `#eval`'d) at runtime against the imported
`.olean`s, so the executable must expose Lean's symbols to interpreted code.
-/
lean_exe nbdsl_worker where
  root := `Worker
  supportInterpreter := true
