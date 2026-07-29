/-
Foundation of the notebook DSL: a thin adapter over Mathlib's category theory.

`Object` is a `def` (not an `abbrev`) so the head symbol `NbDsl.Object C`
survives in DECLARED types — the registry recovers an object's home category
by head-symbol matching on declaration types, which reducibility does not
rewrite. It is `@[reducible]` so that instance search and coercions unfold
it: an `X : Object Groups` then inherits the bundled category's `CoeSort`,
so `∀ a b : X, …` speaks about elements of the carrier and element-level
mathematics applies to DSL objects directly.
-/
import Mathlib.CategoryTheory.Category.Cat

namespace NbDsl

open CategoryTheory

/-- The kind of category the DSL works over: small objects, small homs. -/
abbrev LargeCat := Cat.{0, 1}

/-- An object of a bundled category. -/
@[reducible] def Object (C : LargeCat) : Type 1 := C.α

end NbDsl
