/-
Identifier services for the notebook kernel: `complete` and `inspect`.

REPL-semantics versions: they consult the committed snapshot's environment and
scopes (current namespace, `open`s) rather than InfoTrees of an in-progress
virtual document — that upgrade belongs to the milestone-2 document model.
Cursor offsets are Unicode code points on both sides of the protocol.
-/
import Lean
import Worker.Frontend
import Worker.Output

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

/-- Plain text emitted while probing a plugin-owned expression. The probe
does not commit its candidate state; this is only a query observation. -/
def plainTextOutput? (outputs : Array Worker.Output) : Option String := Id.run do
  let mut found : Option String := none
  for output in outputs do
    for (mime, value) in output.data do
      if mime == "text/plain" then
        match value.getStr? with
        | .ok text => found := some text
        | .error _ => pure ()
  return found

/-- Elaborate an exact query expression through the plugin's real command
surface. This is the extension-state counterpart to environment-constant
queries: successful plugin output proves that the requested object exists in
the current snapshot, while the candidate state and request-local output are
discarded. -/
def probeExpression (cmdState : Elab.Command.State) (code : String)
    : IO (Bool × Option String) := do
  discard Worker.drainOutputs
  let result ← Frontend.processCell cmdState code "<query>"
  let outputs ← Worker.drainOutputs
  let succeeded := !result.messages.any (·.severity matches .error)
  return (succeeded, plainTextOutput? outputs)

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

def runMetaM (cmdState : Elab.Command.State) (x : MetaM α) : IO α := do
  let scope := cmdState.scopes.head!
  let ctx : Core.Context := {
    fileName := "<query>"
    fileMap := FileMap.ofString ""
    options := scope.opts
    currNamespace := scope.currNamespace
    openDecls := scope.openDecls
  }
  let (a, _) ← (x.run').toIO ctx { env := cmdState.env }
  return a

/-- Type-aware dot completion: for `x.pre` where `x` resolves to a global
constant whose type reduces (whnf) to an application headed by constant `C`,
offer `C.*` members — generalized field notation — completing `pre`. `none`
when the shape doesn't apply; the caller falls back to prefix completion. -/
def dotCompletions (cmdState : Elab.Command.State) (code : String) (cursor : Nat)
    : IO (Option (Nat × Array String)) := do
  let (pref, start) := identPrefixAt code cursor
  let parts := pref.splitOn "."
  if parts.length < 2 then return none
  let frag := parts.getLast!
  let headStr := String.intercalate "." parts.dropLast
  if headStr.isEmpty then return none
  let some headName := resolve? cmdState headStr
    | return none
  let some ci := cmdState.env.find? headName
    | return none
  let tyHead ← runMetaM cmdState do
    return (← Meta.whnf ci.type).getAppFn
  let .const tyC _ := tyHead
    | return none
  let found := cmdState.env.constants.fold (init := #[]) fun acc n _ =>
    if n.isInternal || n.hasMacroScopes then acc
    else Id.run do
      if tyC.isPrefixOf n then
        let suffix := n.replacePrefix tyC Name.anonymous
        if nameStartsWith frag.toName suffix && !suffix.isAnonymous then
          return acc.push (headStr ++ "." ++ suffix.toString)
      return acc
  let results := finishResults found
  if results.isEmpty then return none
  return some (start, results)

structure InspectResult where
  name : Name
  type : String
  doc? : Option String

def inspect (cmdState : Elab.Command.State) (code : String) (cursor : Nat)
    : IO (Option InspectResult) := do
  let some name := resolve? cmdState (identAt code cursor)
    | return none
  let some ci := cmdState.env.find? name
    | return none
  let type ← runMetaM cmdState do
    return toString (← Meta.ppExpr ci.type)
  let doc? ← findDocString? cmdState.env name
  return some { name, type, doc? }

end Worker.Query
