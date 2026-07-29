# The NbDsl language

The reference DSL (`dsls/nbdsl/`) explores one idea: **mathematical
bookkeeping that prose leaves implicit — which category an object lives in,
and which functor is silently applied to move it — made explicit, checked,
and queryable**, while every declaration remains an ordinary kernel-checked
Lean definition over mathlib.

For the worked exposition, read/run `dsl-notebooks/nbdsl-example.ipynb`.

## Foundation (`NbDsl/Basic.lean`)

- `LargeCat := Cat.{0,1}` — bundled categories with small objects/homs.
- `Object (C : LargeCat) : Type 1 := C.α` — the objects of `C`.

`Object` is a `@[reducible] def`, and that combination is load-bearing:

- **`def`, not `abbrev` in spirit**: the head symbol `NbDsl.Object C`
  survives in *declared types* (reducibility does not rewrite stored
  types), which is how `#home`/`#via`/`prefer` recover categories by
  head-symbol matching on declaration types.
- **`@[reducible]`**: instance search and coercions unfold it, so a
  declared object inherits its bundled category's `CoeSort` — `X : Object
  Groups` can be used as a type, and `∀ a b : X, a * b = b * a` is
  ordinary element-level mathematics.

## The reducibility chain (why `decide` works on declared objects)

For `by decide` to check a predicate on a declared object, instance search
must reduce the carrier `↥X` all the way to a concrete type (to find
`Fintype`, `DecidableEq`, `Group`, …). Instance search only unfolds
*reducible* definitions, so every link is kept reducible:

| Link | Form | Why |
| --- | --- | --- |
| `Object` | `@[reducible] def` | see above |
| `Sets`, `Groups` | `abbrev` + **structure literal** `⟨GrpCat, inferInstance⟩` | `Cat.of`/`Bundled.of` are non-reducible defs and would stick the chain; projections of literals iota-reduce |
| `let`-declared objects | `noncomputable abbrev` | so `↥S3` unfolds through the declaration |
| `GrpCat.of`, `GrpCat.carrier` | mathlib's own `abbrev`/projection | already reduce |
| `predicate` definitions | `abbrev` | so `Decidable (P X)` sees the body |

Break any link (e.g. define a category via `Cat.of`) and `decide` on
declared objects stops synthesizing `Decidable` instances.

## Commands (`NbDsl/Syntax.lean`)

All are Lean command elaborators; nothing outside Lean interprets them.

### `let X := t ∈ C`

Elaborates to `noncomputable abbrev X : NbDsl.Object C := t` — membership
is a **type ascription**, so a term of the wrong category is a type error
at elaboration, not an annotation mismatch.

### `prefer F`

Registers `F` (which must have declared type `Object C ⥤ Object D`) as the
preferred transport `C → D` in a `SimplePersistentEnvExtension`
(`NbDsl/Registry.lean`). Because the registry lives in the environment,
registrations participate in cell atomicity (a failed cell rolls its
`prefer` back), survive restarts via replay or the olean session cache, and
are visible to tooling.

### `#home X`

Reports `X`'s home category by head-symbol matching on the declaration's
type — a judgment read off the type, not a side table.

### `#via X ∈ D`

Breadth-first search from `X`'s home to `D` through registered functors
(shortest composite). Reports the path as text and emits a structured
`application/vnd.nbdsl.path+json` bundle (`{object, source, target,
steps}`) that the Lab extension renders. No registered path → error; the
system never guesses a functor (e.g. it will not invent the free-group
functor for `Sets → Groups` — register one).

### `predicate P (x ∈ C) := body`

Declares a **method of the category `C`**: elaborates to
`abbrev P : Object C → Prop := fun x => body` and registers `(P, C)` so
`#methods C` can enumerate it. The binder coerces to the carrier, so bodies
are element-level (`∀ a b : x, a * b = b * a`).

Mathematical reading: a well-formed predicate is isomorphism-invariant,
i.e. the object part of a functor `core(C) → Prop` — restricting to the
core (isomorphisms only) is exactly what makes functoriality *be*
iso-invariance, and most predicates arise this way. The POC records the
object part; the morphism-part (iso-invariance) proof obligation is the
designed next refinement.

### `#methods C`

Lists the registered predicates on `C`.

## Standard universe (`NbDsl/Std.lean`)

`import Mathlib` — the whole library is in scope, `sage.all`-style (costs
worker startup and memory, not build time; oleans come from
`lake exe cache get`). Ships `Sets`, `Groups`, the forgetful
`groupsToSets : Object Groups ⥤ Object Sets`, and the generic
`Category (Object C)` instance.

## Parser notes (hard-won)

- The `let` command's value slot is `term:51`: `∈` is a term-level infix at
  precedence 50, so a bare `term` would swallow `∈ C`.
- The `let` command syntax is declared LAST in `Syntax.lean`; declared
  earlier it shadows `let x ← e` in every later `do` block *in that file*
  at parse time. (Notebook cells are unaffected — the prelude is fully
  elaborated before any cell parses.)
- Commands end at newline; a `.` terminator conflicts with field
  projection.
- Lean has no top-level term display: a bare `G` as a cell is a syntax
  error. Inspect with `#check G`, `#home G`, `#eval` (computables), or
  hover.

## Prelude (`NbDsl/Notebook.lean`)

The module a kernel session imports (`--prelude-module`, default
`NbDsl.Notebook`). Importing it is the entire plugin interface — see
[plugins.md](plugins.md).
