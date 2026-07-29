/-
Preferred-functor registry: the DSL's persistent semantic state.

A `SimplePersistentEnvExtension` keeps registrations inside the
`Lean.Environment`, so they participate in command-state snapshots, cell
rollback, and olean import exactly like ordinary declarations. This is what
makes `prefer` a cell-atomic, replayable operation in the notebook: no
semantic DSL state lives outside the environment.
-/
import Lean
import NbDsl.Basic

namespace NbDsl

open Lean

structure FunctorEntry where
  functorName : Name
  src : Name
  tgt : Name
  deriving BEq, Repr, Hashable, Inhabited

initialize preferredFunctorExt :
    SimplePersistentEnvExtension FunctorEntry (Array FunctorEntry) ←
  registerSimplePersistentEnvExtension {
    addEntryFn := Array.push
    addImportedFn := fun arrs => arrs.flatten
  }

def preferredFunctors (env : Environment) : Array FunctorEntry :=
  preferredFunctorExt.getState env

/-- Recover the home category of a declaration of type `NbDsl.Object C` by
head-symbol matching (`Object` is a transparent `def` precisely so the head
survives elaboration). -/
def objectHome? (env : Environment) (obj : Name) : Option Name := do
  let ci ← env.find? obj
  match ci.type with
  | .app (.const ``Object _) (.const cat _) => some cat
  | _ => none

/-- Match `Object C ⥤ Object D` — i.e.
`CategoryTheory.Functor (Object C) instC (Object D) instD` — returning `(C, D)`. -/
def functorEndpoints? (ty : Expr) : Option (Name × Name) := do
  guard <| ty.getAppFn.isConstOf `CategoryTheory.Functor
  let args := ty.getAppArgs
  guard <| args.size == 4
  let src ← matchObject? args[0]!
  let tgt ← matchObject? args[2]!
  return (src, tgt)
where
  matchObject? : Expr → Option Name
    | .app (.const ``Object _) (.const cat _) => some cat
    | _ => none

/-- BFS over registered functors from `src` to `tgt`. Returns the entries of a
shortest path (empty when `src == tgt`), or `none` when unreachable. -/
partial def resolvePath (env : Environment) (src tgt : Name)
    : Option (List FunctorEntry) :=
  go [(src, [])] {}
where
  go (frontier : List (Name × List FunctorEntry)) (visited : NameSet)
      : Option (List FunctorEntry) :=
    match frontier with
    | [] => none
    | (cat, path) :: rest =>
        if cat == tgt then
          some path.reverse
        else if visited.contains cat then
          go rest visited
        else
          let visited := visited.insert cat
          let next := (preferredFunctors env).toList.filterMap fun e =>
            if e.src == cat && !visited.contains e.tgt then
              some (e.tgt, e :: path)
            else none
          go (rest ++ next) visited

end NbDsl
