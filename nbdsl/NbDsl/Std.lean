/-
Standard categories for the notebook DSL: enough of a mathematical universe
to demonstrate declarations, membership, and preferred-functor resolution
over genuine Mathlib category theory.
-/
import Mathlib.CategoryTheory.Types.Basic
import Mathlib.Algebra.Category.Grp.Basic
import Mathlib.Algebra.Group.PUnit
import NbDsl.Basic

namespace NbDsl

open CategoryTheory

/-- Objects of a bundled category form a category (the bundled structure). -/
instance (C : LargeCat) : Category (Object C) := C.str

namespace Std

/-- The category of (small) sets. -/
def Sets : LargeCat := Cat.of (Type 0)

/-- The category of groups. -/
def Groups : LargeCat := Cat.of GrpCat

/-- Underlying-set functor, the canonical `prefer` example. -/
def groupsToSets : Object Groups ⥤ Object Sets := forget GrpCat

end Std
end NbDsl
