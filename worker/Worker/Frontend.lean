/-
Per-cell elaboration for the nbdsl worker.

Adapted from the frontend pattern of `Lean.Elab.Frontend` (Lean core,
Apache-2.0) and the shape of `leanprover-community/repl` (Apache-2.0), both
reimplemented rather than vendored: parse and elaborate one cell's commands
against a retained `Command.State`, collecting this cell's diagnostics and
info trees.

Key deviations from core's frontend, both load-bearing for notebook semantics:
- the end-of-input terminal command is never elaborated, so scopes a cell
  leaves open (a dangling `namespace`/`section`) persist into later cells
  without an "expected end" error;
- an internal elaboration exception becomes an error diagnostic that fails
  the cell instead of crashing the worker.
-/
import Lean

namespace Worker.Frontend

open Lean Lean.Elab

structure Sorry where
  pos : Position
  endPos? : Option Position
  goal : String

structure CellResult where
  cmdState : Command.State
  /-- Only this cell's messages (accumulators are cleared before the run). -/
  messages : List Message
  sorries : Array Sorry

private def mkErrorMessage (ictx : Parser.InputContext) (stx : Syntax)
    (data : MessageData) : Message :=
  { fileName := ictx.fileName
    pos := ictx.fileMap.toPosition (stx.getPos?.getD 0)
    severity := .error
    data }

/--
One parse-elaborate step per command until end of input. Mirrors
`Lean.Elab.Frontend.processCommand` (parser context rebuilt from
`scopes.head!` each step so `namespace`/`open`/`set_option` from earlier
commands — and earlier cells — govern parsing).
-/
private partial def loop (ictx : Parser.InputContext)
    (cancelTk? : Option IO.CancelToken)
    (pstate : Parser.ModuleParserState) (cmdState : Command.State)
    : IO Command.State := do
  let scope := cmdState.scopes.head!
  let pmctx : Parser.ParserModuleContext :=
    { env := cmdState.env, options := scope.opts,
      currNamespace := scope.currNamespace, openDecls := scope.openDecls }
  let (cmd, ps, messages) :=
    Parser.parseCommand ictx pmctx pstate cmdState.messages
  let cmdState := { cmdState with messages := messages }
  if Parser.isTerminalCommand cmd then
    if cmd.isOfKind ``Parser.Command.eoi then
      return cmdState
    else
      -- `import` / `#exit` are module-level; a notebook's imports are fixed
      -- by the prelude, so inside a cell they are errors, not terminators.
      let msg := mkErrorMessage ictx cmd
        m!"cells cannot contain `import` or `#exit`; the notebook prelude fixes the imports"
      return { cmdState with messages := cmdState.messages.add msg }
  else
    let cmdCtx : Command.Context := {
      cmdPos := pstate.pos
      fileName := ictx.fileName
      fileMap := ictx.fileMap
      snap? := none
      cancelTk?
    }
    match ← EIO.toIO' (((Command.elabCommandTopLevel cmd) cmdCtx).run cmdState) with
    | .ok (_, cmdState') =>
        -- `elabCommandTopLevel` RESETS messages and info trees per command
        -- (modern Lean reports them through the snapshot machinery instead);
        -- a multi-command cell must accumulate them across commands here or
        -- only the last command's diagnostics and sorries survive.
        let merged := { cmdState' with
          messages := cmdState.messages ++ cmdState'.messages
          infoState := { cmdState'.infoState with
            trees := cmdState'.infoState.trees.foldl (·.push ·)
              cmdState.infoState.trees } }
        loop ictx cancelTk? ps merged
    | .error e =>
        -- Internal error (elabCommandTopLevel logs ordinary elaboration
        -- errors itself): fail the cell, keep the worker alive.
        let msg := mkErrorMessage ictx cmd e.toMessageData
        return { cmdState with messages := cmdState.messages.add msg }

/-- Collect sorries from this cell's info trees, repl-style. -/
private def collectSorries (ictx : Parser.InputContext)
    (trees : PersistentArray InfoTree) : IO (Array Sorry) := do
  let mut out := #[]
  for tree in trees do
    let entries ← tree.foldInfoM (init := #[]) fun ci info acc => do
      match info with
      | .ofTacticInfo ti =>
          if ti.stx.isOfKind ``Parser.Tactic.tacticSorry then
            let goal ← ci.runMetaM {} do
              let fmts ← ti.goalsBefore.mapM Meta.ppGoal
              return String.intercalate "\n\n" (fmts.map toString)
            return acc.push (mkSorry ti.stx goal)
          else
            return acc
      | .ofTermInfo ti =>
          if ti.expr.isSorry then
            let goal ← ci.runMetaM ti.lctx do
              match ti.expectedType? with
              | some t => return s!"⊢ {← Meta.ppExpr t}"
              | none => return "⊢ ?"
            return acc.push (mkSorry ti.stx goal)
          else
            return acc
      | _ => return acc
    out := out ++ entries
  -- The tactic form also elaborates an equivalent term at the same position;
  -- keep the first (tactic) entry per position.
  let mut seen : Std.HashSet (Nat × Nat) := {}
  let mut deduped := #[]
  for s in out do
    if !seen.contains (s.pos.line, s.pos.column) then
      seen := seen.insert (s.pos.line, s.pos.column)
      deduped := deduped.push s
  return deduped
where
  mkSorry (stx : Syntax) (goal : String) : Sorry :=
    { pos := ictx.fileMap.toPosition (stx.getPos?.getD 0)
      endPos? := stx.getTailPos?.map ictx.fileMap.toPosition
      goal }

/--
Parse (without elaborating) to classify a cell for Jupyter's `is_complete`:
`"complete"` when Lean's parser accepts every command, `"incomplete"` when
the only failure is at end of input (an unclosed construct), `"invalid"` on a
definite syntax error. Python never guesses at Lean syntax.
-/
partial def classifyInput (parent : Command.State) (code : String) : String :=
  let ictx := Parser.mkInputContext code "<is_complete>"
  let endPos := ictx.fileMap.toPosition ⟨code.utf8ByteSize⟩
  go ictx endPos {} { parent with messages := {} }
where
  go (ictx : Parser.InputContext) (endPos : Position)
      (pstate : Parser.ModuleParserState) (cmdState : Command.State) : String :=
    let scope := cmdState.scopes.head!
    let pmctx : Parser.ParserModuleContext :=
      { env := cmdState.env, options := scope.opts,
        currNamespace := scope.currNamespace, openDecls := scope.openDecls }
    let (cmd, ps, messages) :=
      Parser.parseCommand ictx pmctx pstate cmdState.messages
    let errs := messages.toList.filter (·.severity matches .error)
    if errs.isEmpty then
      if Parser.isTerminalCommand cmd then "complete"
      else go ictx endPos ps { cmdState with messages := messages }
    else if errs.all fun m => m.pos.line == endPos.line && m.pos.column == endPos.column then
      "incomplete"
    else
      "invalid"

/-- Byte position of a code-point offset (protocol cursors are code points). -/
def codepointPos (s : String) (cp : Nat) : String.Pos.Raw := Id.run do
  let mut byteIdx := 0
  let mut n := 0
  for c in s.toList do
    if n == cp then
      return ⟨byteIdx⟩
    byteIdx := byteIdx + c.utf8Size
    n := n + 1
  return ⟨byteIdx⟩

/--
Elaborate one cell against `parent`. The returned state is a *candidate*: the
caller commits it only when no diagnostic has error severity.
-/
def processCell (parent : Command.State) (code : String) (fileName : String)
    (cancelTk? : Option IO.CancelToken := none) : IO CellResult := do
  let ictx := Parser.mkInputContext code fileName
  -- Clear per-request accumulators; every semantic field (env, scopes,
  -- options, macro scopes, name generators) is retained.
  let initial : Command.State :=
    { parent with messages := {}, infoState := { enabled := true }, traceState := {} }
  let final ← loop ictx cancelTk? {} initial
  let sorries ← collectSorries ictx final.infoState.trees
  return { cmdState := final, messages := final.messages.toList, sorries }

end Worker.Frontend
