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
import Worker.Query
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

def handleExecute (session : IO.Ref Session) (cancelTk : IO.CancelToken)
    (req : Json) : IO Json := do
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
  let result ← Frontend.processCell parent.cmdState code s!"<{cellId}>" (some cancelTk)
  let outputs ← NbDsl.Notebook.drainOutputs
  let diags ← result.messages.mapM diagnosticJson
  let hasError := result.messages.any (·.severity matches .error)
  let common :=
    [("diagnostics", Json.arr diags.toArray),
     ("sorries", Json.arr (result.sorries.map sorryJson)),
     ("outputs", Json.arr (outputs.map (·.toJson)))]
  if ← cancelTk.isSet then
    -- Cancelled cooperatively: nothing commits, parent stays current.
    return reply req <| [("status", Json.str "cancelled"), ("snapshot", toJson parentId)] ++ common
  else if hasError then
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

/-- In-flight execute: its request id and cancellation token. -/
abbrev Inflight := IO.Ref (Option (String × IO.CancelToken))

def handleRequest (session : IO.Ref Session) (inflight : Inflight)
    (req : Json) : IO Json := do
  match req.getObjValAs? String "op" with
  | .ok "execute" =>
      let tk ← IO.CancelToken.new
      if let .ok rid := req.getObjValAs? String "request_id" then
        inflight.set (some (rid, tk))
      let rep ← handleExecute session tk req
      inflight.set none
      return rep
  | .ok "is_complete" =>
      let .ok code := req.getObjValAs? String "code"
        | return reply req [("status", Json.str "error"), ("message", Json.str "missing code")]
      let s ← session.get
      let some parent := s.snapshots[s.current]?
        | return reply req
            [("status", Json.str "error"), ("message", Json.str "invalid current snapshot")]
      return reply req
        [("status", Json.str "ok"),
         ("result", Json.str (Frontend.classifyInput parent.cmdState code))]
  | .ok "complete" =>
      let .ok code := req.getObjValAs? String "code"
        | return reply req [("status", Json.str "error"), ("message", Json.str "missing code")]
      let .ok cursor := req.getObjValAs? Nat "cursor"
        | return reply req [("status", Json.str "error"), ("message", Json.str "missing cursor")]
      let s ← session.get
      let some parent := s.snapshots[s.current]?
        | return reply req
            [("status", Json.str "error"), ("message", Json.str "invalid current snapshot")]
      let (_, start, results) := Query.completions parent.cmdState code cursor
      return reply req
        [("status", Json.str "ok"),
         ("matches", Json.arr (results.map Json.str)),
         ("cursor_start", toJson start),
         ("cursor_end", toJson cursor)]
  | .ok "inspect" =>
      let .ok code := req.getObjValAs? String "code"
        | return reply req [("status", Json.str "error"), ("message", Json.str "missing code")]
      let .ok cursor := req.getObjValAs? Nat "cursor"
        | return reply req [("status", Json.str "error"), ("message", Json.str "missing cursor")]
      let s ← session.get
      let some parent := s.snapshots[s.current]?
        | return reply req
            [("status", Json.str "error"), ("message", Json.str "invalid current snapshot")]
      match ← Query.inspect parent.cmdState code cursor with
      | none => return reply req [("status", Json.str "ok"), ("found", toJson false)]
      | some r =>
          return reply req
            [("status", Json.str "ok"),
             ("found", toJson true),
             ("name", Json.str r.name.toString),
             ("type", Json.str r.type),
             ("doc", r.doc?.elim Json.null Json.str)]
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

/--
Reader task: the only reader of the request fd. Ordinary requests are queued
for the main task; `cancel` frames are handled out-of-band by setting the
in-flight execute's cancellation token (they get no reply of their own — the
cancelled execute replies `status:"cancelled"`).
-/
partial def readerLoop (ch : Channel) (queue : Std.CloseableChannel.Sync Json)
    (inflight : Inflight) : IO Unit := do
  match ← readFrame ch with
  | none => return ()   -- clean EOF
  | some req =>
      if let .ok "cancel" := req.getObjValAs? String "op" then
        if let .ok rid := req.getObjValAs? String "request_id" then
          if let some (cur, tk) ← inflight.get then
            if cur == rid then tk.set
        readerLoop ch queue inflight
      else
        match ← (queue.send req).toBaseIO with
        | .ok _ => readerLoop ch queue inflight
        | .error _ => return ()

/--
Run the reader and, no matter how it ends — clean EOF, a torn frame from a
dying kernel, any exception — close the queue so the main task's `recv`
resolves and the process can exit. Without this a reader failure leaves the
worker orphaned forever (observed: futex-parked main task, no pipe reader).
-/
def readerTask (ch : Channel) (queue : Std.CloseableChannel.Sync Json)
    (inflight : Inflight) : IO Unit := do
  try
    readerLoop ch queue inflight
  finally
    discard (queue.close).toBaseIO

partial def mainLoop (ch : Channel) (queue : Std.CloseableChannel.Sync Json)
    (session : IO.Ref Session) (inflight : Inflight) : IO Unit := do
  match ← queue.recv with
  | none => return ()   -- queue closed after EOF: clean shutdown
  | some req =>
      writeFrame ch (← handleRequest session inflight req)
      mainLoop ch queue session inflight

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
      let inflight : Worker.Inflight ← IO.mkRef none
      let queue ← Std.CloseableChannel.Sync.new
      let _reader ← IO.asTask (Worker.readerTask ch queue inflight) .dedicated
      writeFrame ch <| Json.mkObj
        [("op", Json.str "ready"),
         ("protocol", toJson (1 : Nat)),
         ("lean", Json.str Lean.versionString),
         ("snapshot", toJson (0 : Nat))]
      Worker.mainLoop ch queue session inflight
      return 0
