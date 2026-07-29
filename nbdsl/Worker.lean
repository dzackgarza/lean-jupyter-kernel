/-
nbdsl_worker — persistent Lean frontend for the notebook-DSL Jupyter kernel.

The Jupyter kernel (Python, nbdsl_kernel/) is a thin protocol adapter; this
process owns parsing, elaboration, semantic state, and proof checking. Cells
arrive verbatim over the framed-JSON control channel (Worker/Protocol.lean)
and are elaborated against retained `Command.State` snapshots
(Worker/Frontend.lean).

Cell atomicity: a cell's candidate state is committed as a new snapshot only
when the cell produced no error-severity diagnostic; otherwise the parent
snapshot remains current and the diagnostics are reported.
-/
import Worker.Protocol
import Worker.Frontend
import NbDsl.Notebook.Output

open Worker.Protocol
open Lean (Json toJson)

namespace Worker

structure WorkerArgs where
  reqFd : Nat
  repFd : Nat
  /-- Module elaborated once at startup as the fixed notebook prelude. -/
  preludeModule : Lean.Name := `Init

def parseWorkerArgs (argv : List String) : Except String WorkerArgs := do
  let rec go : List String → WorkerArgs → Except String WorkerArgs
    | [], acc => .ok acc
    | "--req-fd" :: n :: rest, acc =>
        match n.toNat? with
        | some v => go rest { acc with reqFd := v }
        | none => .error s!"--req-fd expects a number, got {n}"
    | "--rep-fd" :: n :: rest, acc =>
        match n.toNat? with
        | some v => go rest { acc with repFd := v }
        | none => .error s!"--rep-fd expects a number, got {n}"
    | "--prelude-module" :: m :: rest, acc =>
        go rest { acc with preludeModule := m.toName }
    | arg :: _, _ => .error s!"unknown argument {arg}"
  let parsed ← go argv { reqFd := 0, repFd := 0 }
  if parsed.reqFd == 0 || parsed.repFd == 0 then
    .error "usage: nbdsl_worker --req-fd N --rep-fd M [--prelude-module Mod]"
  else
    .ok parsed

structure Snapshot where
  id : Nat
  parent? : Option Nat
  cmdState : Lean.Elab.Command.State
  cellId : String

structure Session where
  /-- Snapshot DAG; ids are indices. `Command.State` is a persistent pure
  value, so retaining it is the whole snapshot mechanism. -/
  snapshots : Array Snapshot
  current : Nat

/-- Echo the request id (if any) into a reply object. -/
def reply (req : Json) (fields : List (String × Json)) : Json :=
  match req.getObjValAs? String "request_id" with
  | .ok rid => Json.mkObj (("request_id", Json.str rid) :: fields)
  | .error _ => Json.mkObj fields

def positionJson (p : Lean.Position) : Json :=
  Json.mkObj [("line", toJson p.line), ("column", toJson p.column)]

/-- Columns are Unicode code points (`FileMap.toPosition` counts characters),
matching Jupyter's `cursor_pos` convention; no conversion happens in Python. -/
def diagnosticJson (m : Lean.Message) : IO Json := do
  let s ← m.serialize
  return Json.mkObj
    [("severity", Json.str (toString s.severity)),
     ("message", Json.str s.data),
     ("start", positionJson s.pos),
     ("end", s.endPos.elim Json.null positionJson)]

def sorryJson (s : Frontend.Sorry) : Json :=
  Json.mkObj
    [("start", positionJson s.pos),
     ("end", s.endPos?.elim Json.null positionJson),
     ("goal", Json.str s.goal)]

def handleExecute (session : IO.Ref Session) (req : Json) : IO Json := do
  let .ok code := req.getObjValAs? String "code"
    | return reply req [("status", Json.str "error"), ("message", Json.str "missing code")]
  let cellId := (req.getObjValAs? String "cell_id").toOption.getD "cell"
  let s ← session.get
  let parentId := (req.getObjValAs? Nat "parent_snapshot").toOption.getD s.current
  let some parent := s.snapshots[parentId]?
    | return reply req
        [("status", Json.str "error"),
         ("message", Json.str s!"unknown snapshot {parentId}")]
  -- Request-local output sink: clear leftovers, elaborate, drain.
  discard NbDsl.Notebook.drainOutputs
  let result ← Frontend.processCell parent.cmdState code s!"<{cellId}>"
  let outputs ← NbDsl.Notebook.drainOutputs
  let diags ← result.messages.mapM diagnosticJson
  let hasError := result.messages.any (·.severity matches .error)
  let common :=
    [("diagnostics", Json.arr diags.toArray),
     ("sorries", Json.arr (result.sorries.map sorryJson)),
     ("outputs", Json.arr (outputs.map (·.toJson)))]
  if hasError then
    -- Failure isolation: the parent snapshot stays current.
    return reply req <| [("status", Json.str "error"), ("snapshot", toJson parentId)] ++ common
  else
    let id := s.snapshots.size
    session.set {
      snapshots := s.snapshots.push
        { id, parent? := some parentId, cmdState := result.cmdState, cellId }
      current := id
    }
    return reply req <| [("status", Json.str "ok"), ("snapshot", toJson id)] ++ common

def handleRequest (session : IO.Ref Session) (req : Json) : IO Json := do
  match req.getObjValAs? String "op" with
  | .ok "execute" => handleExecute session req
  | .ok "describe" =>
      let s ← session.get
      return reply req
        [("status", Json.str "ok"),
         ("protocol", toJson (1 : Nat)),
         ("lean", Json.str Lean.versionString),
         ("snapshot", toJson s.current),
         ("snapshot_count", toJson s.snapshots.size)]
  | .ok op =>
      return reply req
        [("status", Json.str "unsupported"), ("op", Json.str op)]
  | .error _ =>
      return reply req
        [("status", Json.str "error"), ("message", Json.str "missing op")]

partial def mainLoop (ch : Channel) (session : IO.Ref Session) : IO Unit := do
  match ← readFrame ch with
  | none => return ()   -- parent closed the request pipe: clean shutdown
  | some req =>
      writeFrame ch (← handleRequest session req)
      mainLoop ch session

/-- Import the prelude module and build snapshot 0. -/
unsafe def initSession (preludeModule : Lean.Name) : IO Session := do
  Lean.initSearchPath (← Lean.findSysroot)
  Lean.enableInitializersExecution
  let env ← Lean.importModules #[{ module := preludeModule }] {} (loadExts := true)
  let cmdState := Lean.Elab.Command.mkState env {} {}
  let cmdState := { cmdState with infoState.enabled := true }
  return {
    snapshots := #[{ id := 0, parent? := none, cmdState, cellId := "<prelude>" }]
    current := 0
  }

end Worker

unsafe def main (argv : List String) : IO UInt32 := do
  match Worker.parseWorkerArgs argv with
  | .error e =>
      IO.eprintln s!"nbdsl_worker: {e}"
      return 2
  | .ok args =>
      let ch ← openChannel args.reqFd args.repFd
      let session ← IO.mkRef (← Worker.initSession args.preludeModule)
      writeFrame ch <| Json.mkObj
        [("op", Json.str "ready"),
         ("protocol", toJson (1 : Nat)),
         ("lean", Json.str Lean.versionString),
         ("snapshot", toJson (0 : Nat))]
      Worker.mainLoop ch session
      return 0
