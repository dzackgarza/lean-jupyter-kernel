/-
Identifier services for the notebook kernel: `complete` and `inspect`.

REPL-semantics versions: they consult the committed snapshot's environment and
scopes (current namespace, `open`s) rather than InfoTrees of an in-progress
virtual document — that upgrade belongs to the milestone-2 document model.
Cursor offsets are Unicode code points on both sides of the protocol.
-/
import Lean
import Worker.Cell

namespace Worker.Query

open Lean

def isIdentChar (c : Char) : Bool :=
  isIdFirst c || isIdRest c || c == '.'

/-- The identifier fragment ending at `cursor` (code points): `(text, start)`. -/
def identPrefixAt (code : String) (cursor : Nat) : String × Nat := Id.run do
  let chars := code.toList.toArray
  let cursor := min cursor chars.size
  let mut start := cursor
  while start > 0 && isIdentChar chars[start - 1]! do
    start := start - 1
  return (String.ofList (chars.extract start cursor).toList, start)

/-- The whole identifier under `cursor`, extended in both directions. -/
def identAt (code : String) (cursor : Nat) : String := Id.run do
  let chars := code.toList.toArray
  let cursor := min cursor chars.size
  let mut start := cursor
  while start > 0 && isIdentChar chars[start - 1]! do
    start := start - 1
  let mut stop := cursor
  while stop < chars.size && isIdentChar chars[stop]! do
    stop := stop + 1
  return String.ofList (chars.extract start stop).toList

/-- Namespaces a bare name may be resolved against, most specific first:
prefixes of the current namespace, then simple opens, then root. -/
def resolutionNamespaces (scope : Elab.Command.Scope) : List Name := Id.run do
  let mut nss := []
  let mut ns := scope.currNamespace
  while !ns.isAnonymous do
    nss := nss ++ [ns]
    ns := ns.getPrefix
  for d in scope.openDecls do
    if let .simple opened _ := d then
      nss := nss ++ [opened]
  return nss

/-- Sorted, deduplicated, capped — the shared shape of completion results. -/
private def finishResults (found : Array String) : Array String := Id.run do
  let mut results : Array String := #[]
  for s in found.qsort (· < ·) do
    if results.back? != some s then
      results := results.push s
  if results.size > 100 then
    results := results.extract 0 100
  return results

private def prefixAtDepth : Name → Nat → Name
  | _, 0 => .anonymous
  | .anonymous, _ + 1 => .anonymous
  | n@(.str p _), depth =>
      if depth <= p.getNumParts then prefixAtDepth p depth else n
  | n@(.num p _), depth =>
      if depth <= p.getNumParts then prefixAtDepth p depth else n

private def firstComponent : Name → Name
  | .anonymous => .anonymous
  | n@(.str .anonymous _) => n
  | n@(.num .anonymous _) => n
  | .str p _ => firstComponent p
  | .num p _ => firstComponent p

private def nameStartsWith (pfx candidate : Name) : Bool :=
  match pfx with
  | .str .anonymous pfxAtom =>
      match firstComponent candidate with
      | .str _ candidateAtom => pfxAtom.isPrefixOf candidateAtom
      | _ => false
  | _ =>
      let pfxDepth := pfx.getNumParts
      if pfxDepth == 0 || candidate.getNumParts < pfxDepth then
        false
      else
        let parentDepth := pfxDepth - 1
        let candidateParent := prefixAtDepth candidate parentDepth
        if candidateParent != pfx.getPrefix then
          false
        else
          let candidatePfx := prefixAtDepth candidate pfxDepth
          match pfx, candidatePfx with
          | .str _ pfx, .str _ candidate => pfx.isPrefixOf candidate
          | _, _ => false

def completions (cmdState : Elab.Command.State) (code : String) (cursor : Nat)
    : String × Nat × Array String := Id.run do
  let (pref, start) := identPrefixAt code cursor
  if pref.isEmpty then
    return (pref, start, #[])
  let scope := cmdState.scopes.head!
  let namespaces := resolutionNamespaces scope
  let prefName := pref.toName
  let found := cmdState.env.constants.fold (init := #[]) fun acc n _ =>
    if n.isInternal || n.hasMacroScopes then acc
    else Id.run do
      if nameStartsWith prefName n then
        return acc.push n.toString
      for ns in namespaces do
        if ns.isPrefixOf n then
          let short := n.replacePrefix ns Name.anonymous
          if nameStartsWith prefName short then
            return acc.push short.toString
      return acc
  return (pref, start, finishResults found)

/-- Resolve `ident` the way a cell would: against the current namespace
chain, then opens, then the root namespace. -/
def resolve? (cmdState : Elab.Command.State) (ident : String) : Option Name := Id.run do
  if ident.isEmpty then return none
  let name := ident.toName
  let scope := cmdState.scopes.head!
  for ns in resolutionNamespaces scope do
    let candidate := ns ++ name
    if cmdState.env.contains candidate then
      return some candidate
  if cmdState.env.contains name then
    return some name
  return none

/-- Purely syntactic completion and lookup in the committed environment.
Neither candidate elaboration, native reduction, extensible pretty-printers nor
documentation callbacks occur at this boundary. -/
def retainedCompletions (cmdState : Elab.Command.State) (code : String) (cursor : Nat) :
    Nat × Array String := Id.run do
  let (stem, start, names) := completions cmdState code cursor
  let supplied := (Cell.getObservations cmdState.env).filterMap fun item =>
    if stem.isPrefixOf item.name then some item.name else none
  return (start, finishResults (names ++ supplied))

structure InspectResult where
  name : String
  type : String
  doc? : Option String

def inspect (cmdState : Elab.Command.State) (code : String) (cursor : Nat) :
    Option InspectResult := do
  let ident := identAt code cursor
  if let some entry := (Cell.getObservations cmdState.env).find? (·.name == ident) then
    return { name := entry.name, type := entry.type, doc? := entry.doc }
  let name ← resolve? cmdState ident
  let ci ← cmdState.env.find? name
  -- Expr's structural representation is pure and cannot run a delaborator.
  return { name := name.toString, type := toString ci.type, doc? := none }

end Worker.Query
