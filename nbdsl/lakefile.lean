import Lake
open Lake DSL

package nbdsl where
  version := v!"0.1.0"

require mathlib from git
  "https://github.com/leanprover-community/mathlib4.git" @ "v4.32.0"

@[default_target]
lean_lib NbDsl

/-- The worker's own modules (`Worker`, `Worker.Protocol`, `Worker.Frontend`). -/
lean_lib Worker

/--
The persistent notebook worker. `supportInterpreter` is required because cells
are elaborated (and `#eval`'d) at runtime against the imported `.olean`s, so
the executable must expose Lean's symbols to interpreted code.
-/
lean_exe nbdsl_worker where
  root := `Worker
  supportInterpreter := true
