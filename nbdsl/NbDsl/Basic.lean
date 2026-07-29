/-
Foundation of the notebook DSL: a thin adapter over Mathlib's category theory.

`Object` is a transparent `def` (not an `abbrev`) on purpose: the registry
recovers an object's home category by head-symbol matching on `NbDsl.Object C`,
so the head must survive in elaborated types without unfolding eagerly.
-/
import Mathlib.CategoryTheory.Category.Cat

namespace NbDsl

open CategoryTheory

/-- The kind of category the DSL works over: small objects, small homs. -/
abbrev LargeCat := Cat.{0, 1}

/-- An object of a bundled category. -/
def Object (C : LargeCat) : Type 1 := C.α

end NbDsl
