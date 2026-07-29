/-
Standard categories for the notebook DSL: enough of a mathematical universe
to demonstrate declarations, membership, and preferred-functor resolution
over genuine Mathlib category theory.
-/
-- All of mathlib, sage.all-style: in a notebook you want the whole library
-- in scope. Costs worker startup time and memory, not build time (oleans
-- come prebuilt from `lake exe cache get`).
import Mathlib
import NbDsl.Basic

namespace NbDsl

open CategoryTheory

/-- Objects of a bundled category form a category (the bundled structure). -/
instance (C : LargeCat) : Category (Object C) := C.str

namespace Std

/-- The category of (small) sets. Structure literal rather than `Cat.of`
(a non-reducible def) so `Object Sets` reduces to `Type 0` by projection —
which is what lets declared objects be used as types and lets `decide`
find carrier instances. -/
abbrev Sets : LargeCat := ⟨Type 0, inferInstance⟩

/-- The category of groups. See `Sets` for why this is a structure literal. -/
abbrev Groups : LargeCat := ⟨GrpCat, inferInstance⟩

/-- Underlying-set functor, the canonical `prefer` example. -/
def groupsToSets : Object Groups ⥤ Object Sets := forget GrpCat

end Std
end NbDsl
