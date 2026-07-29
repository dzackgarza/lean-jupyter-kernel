import Lake
open Lake DSL

/-
The reference DSL plugin. A DSL package provides its library plus a prelude
module (here `NbDsl.Notebook`) and depends on the core only through the
`Worker` library — see the repo README, "Bring your own DSL".
-/
package nbdsl where
  version := v!"0.1.0"

require «nbdsl-worker» from ".." / ".." / "worker"

require mathlib from git
  "https://github.com/leanprover-community/mathlib4.git" @ "v4.32.0"

@[default_target]
lean_lib NbDsl
