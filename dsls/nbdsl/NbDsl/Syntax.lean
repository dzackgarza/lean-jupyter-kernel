/-
Surface syntax of the notebook DSL — command elaborators only; Python never
interprets any of this, cells reach Lean verbatim.

Parser notes (hard-won, load-bearing):
- The declaration command's value slot must be `term:51`: `∈` is a term-level
  infix at precedence 50, so a bare `term` would swallow `∈ 𝒞`.
- The `let` command syntax is declared LAST in this file; declared earlier it
  shadows `let x ← e` inside every subsequent `do` block at parse time.
- Commands end at newline; a `.` terminator conflicts with field projection.
-/
import Lean
import NbDsl.Registry
import Worker.Output

namespace NbDsl.DSL

open Lean Elab Command
open Worker (emitOutput)

syntax (name := dslPrefer) "prefer " ident : command
syntax (name := dslHome) "#home " ident : command
syntax (name := dslVia) "#via " ident " ∈ " ident : command

@[command_elab dslPrefer]
def elabPrefer : CommandElab := fun stx => do
  let fn : Ident := ⟨stx[1]⟩
  let name ← liftCoreM <| realizeGlobalConstNoOverload fn
  let env ← getEnv
  let some ci := env.find? name
    | throwError "unknown declaration {name}"
  let some (src, tgt) := functorEndpoints? ci.type
    | throwError "{name} is not a DSL functor (expected type `Object C ⥤ Object D`)"
  modifyEnv fun env =>
    preferredFunctorExt.addEntry env { functorName := name, src, tgt }
  logInfo m!"preferred: {name} : {src} ⥤ {tgt}"

@[command_elab dslHome]
def elabHome : CommandElab := fun stx => do
  let obj : Ident := ⟨stx[1]⟩
  let name ← liftCoreM <| realizeGlobalConstNoOverload obj
  match objectHome? (← getEnv) name with
  | some cat => logInfo m!"{name} ∈ {cat}"
  | none => throwError "{name} is not a DSL object (expected type `NbDsl.Object C`)"

@[command_elab dslVia]
def elabVia : CommandElab := fun stx => do
  let obj : Ident := ⟨stx[1]⟩
  let catId : Ident := ⟨stx[3]⟩
  let objName ← liftCoreM <| realizeGlobalConstNoOverload obj
  let tgt ← liftCoreM <| realizeGlobalConstNoOverload catId
  let env ← getEnv
  let some src := objectHome? env objName
    | throwError "{objName} is not a DSL object (expected type `NbDsl.Object C`)"
  let some path := resolvePath env src tgt
    | throwError "no preferred-functor path from {src} to {tgt}"
  let steps := path.map (·.functorName)
  let chain := " → ".intercalate ((src :: path.map (·.tgt)).map toString)
  logInfo m!"{objName} ∈ {tgt} via {chain}"
  emitOutput {
    data :=
      [("text/plain", .str s!"{objName} ∈ {tgt} via {chain}"),
       ("application/vnd.nbdsl.path+json", Json.mkObj
         [("object", .str objName.toString),
          ("source", .str src.toString),
          ("target", .str tgt.toString),
          ("steps", .arr (steps.map (Json.str ·.toString)).toArray)])]
  }

/-- Predicate command: `predicate P (x ∈ C) := body` declares a "method" of
the category `C` — an ordinary kernel-checked `abbrev P (x : Object C) :
Prop := body` (reducible so `decide` can see through it on concrete
objects), registered so `#methods C` can enumerate it. The binder `x`
coerces to the object's carrier, so element-level bodies like
`∀ a b : x, a * b = b * a` read naturally. -/
syntax (name := dslPredicate)
  "predicate " ident "(" ident " ∈ " ident ")" " := " term : command

@[command_elab dslPredicate]
def elabPredicate : CommandElab := fun stx => do
  let pName : Ident := ⟨stx[1]⟩
  let binder : Ident := ⟨stx[3]⟩
  let catId : Ident := ⟨stx[5]⟩
  let body : Term := ⟨stx[8]⟩
  let catName ← liftCoreM <| realizeGlobalConstNoOverload catId
  elabCommand
    (← `(command| abbrev $pName : NbDsl.Object $catId → Prop :=
          fun $binder => $body))
  let full := (← getCurrNamespace) ++ pName.getId
  modifyEnv fun env =>
    predicateExt.addEntry env { predName := full, category := catName }
  logInfo m!"predicate: {full} on {catName}"

syntax (name := dslMethods) "#methods " ident : command

@[command_elab dslMethods]
def elabMethods : CommandElab := fun stx => do
  let catId : Ident := ⟨stx[1]⟩
  let catName ← liftCoreM <| realizeGlobalConstNoOverload catId
  let preds := predicatesOn (← getEnv) catName
  if preds.isEmpty then
    logInfo m!"{catName} has no registered predicates"
  else
    logInfo m!"predicates on {catName}: {preds.toList}"

/-- Declaration command: `let X := t ∈ C` elaborates to an ordinary
kernel-checked declaration `noncomputable def X : NbDsl.Object C := t`.
Declared last in this file — see the parser notes in the header. -/
syntax (name := dslLetDef) "let " ident " := " term:51 " ∈ " term : command

@[command_elab dslLetDef]
def elabLetDef : CommandElab := fun stx => do
  let name : Ident := ⟨stx[1]⟩
  let value : Term := ⟨stx[3]⟩
  let category : Term := ⟨stx[5]⟩
  -- `abbrev` (reducible) so the declared object unfolds to its construction:
  -- `↥X` then reduces all the way to the carrier type, making element-level
  -- statements and `decide` work on declared objects directly.
  elabCommand
    (← `(command| noncomputable abbrev $name : NbDsl.Object $category := $value))

end NbDsl.DSL
