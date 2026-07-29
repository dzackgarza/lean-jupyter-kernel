/-
The notebook prelude: the single module every kernel session imports before
the first cell. Cells are ordinary Lean top-level commands elaborated against
this environment — the same text means the same thing in a notebook and in a
`.lean` file importing this module.
-/
import NbDsl.Basic
import NbDsl.Registry
import NbDsl.Syntax
import NbDsl.Std
import Worker.Output
