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
import Worker.Output
import Worker.SessionCache
import Worker.ReleaseInfo

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
  discard drainOutputs
  let result ← Frontend.processCell parent.cmdState code s!"<{cellId}>" (some cancelTk)
  let outputs ← drainOutputs
  let diags ← result.messages.mapM diagnosticJson
  let hasError := result.messages.any (·.severity matches .error)
  -- A cell is one unit for publishing: on error or cancel, discard any
  -- prefix `emitOutput` bundles so notebooks never render rich results under
  -- a failed cell (issue #11). Snapshot rollback is separate and already
  -- keeps the parent current below.
  let published :=
    if hasError || (← cancelTk.isSet) then #[] else outputs
  let common :=
    [("diagnostics", Json.arr diags.toArray),
     ("sorries", Json.arr (result.sorries.map sorryJson)),
     ("outputs", Json.arr (published.map (·.toJson)))]
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
      -- Type-aware dot completion first; plain prefix completion otherwise.
      -- v1 queries Lean-environment names only (no extension-expression probe).
      let (start, results) ←
        match ← Query.dotCompletions parent.cmdState code cursor with
        | some (start, results) => pure (start, results)
        | none =>
            let (_, start, results) :=
              Query.completions parent.cmdState code cursor
            pure (start, results)
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
      -- Analysis-only elaboration of the cell (candidate state discarded, no
      -- commit): the InfoTrees give server-grade hover — locals included —
      -- via `Info.fmtHover?`. Note: like the language server, analysis runs
      -- the cell's elaboration, so `#eval` side effects execute.
      let hover? ← do
        let result ← Frontend.processCell parent.cmdState code "<inspect>"
        discard drainOutputs
        let pos := Frontend.codepointPos code cursor
        let mut found : Option String := none
        for tree in result.cmdState.infoState.trees do
          if let some iwc := tree.hoverableInfoAtM? (m := Id) pos (includeStop := true) then
            -- Only an identifier-anchored info describes what was asked
            -- about. A plugin's low-priority catch-all production (a bare
            -- `term : command`) matches ANY cell, and the info covering the
            -- position is then that syntax declaration — whose hover is its
            -- own docstring, returned identically for every input. Inspect
            -- must discriminate, so non-identifier infos fall through to the
            -- environment lookup below instead of answering for them.
            if iwc.info.stx.isIdent then
              if let some f ← Lean.Elab.Info.fmtHover? iwc.ctx iwc.info then
                found := some (toString f.fmt)
                break
        pure found
      -- Environment fallback still supplies name/type/doc when it resolves.
      let global? ← Query.inspect parent.cmdState code cursor
      if hover?.isNone && global?.isNone then
        return reply req [("status", Json.str "ok"), ("found", toJson false)]
      let mut fields := [("status", Json.str "ok"), ("found", toJson true)]
      if let some h := hover? then
        fields := fields ++ [("hover", Json.str h)]
      if let some r := global? then
        fields := fields ++
          [("name", Json.str r.name.toString),
           ("type", Json.str r.type),
           ("doc", r.doc?.elim Json.null Json.str)]
      return reply req fields
  | .ok "save_session" =>
      let .ok dir := req.getObjValAs? String "path"
        | return reply req [("status", Json.str "error"), ("message", Json.str "missing path")]
      let s ← session.get
      let some snap := s.snapshots[s.current]?
        | return reply req
            [("status", Json.str "error"), ("message", Json.str "invalid current snapshot")]
      (match ← SessionCache.save snap.cmdState dir with
       | .ok () => return reply req [("status", Json.str "ok"), ("saved", toJson true)]
       | .error reason =>
           return reply req
             [("status", Json.str "ok"), ("saved", toJson false),
              ("reason", Json.str reason)])
  | .ok "load_session" =>
      let .ok dir := req.getObjValAs? String "path"
        | return reply req [("status", Json.str "error"), ("message", Json.str "missing path")]
      match ← (SessionCache.load dir).toBaseIO with
      | .error e =>
          return reply req
            [("status", Json.str "error"), ("message", Json.str s!"cache miss: {e}")]
      | .ok cmdState =>
          let s ← session.get
          let id := s.snapshots.size
          session.set {
            snapshots := s.snapshots.push
              { id, parent? := none, cmdState, cellId := "<restored>" }
            current := id
          }
          return reply req [("status", Json.str "ok"), ("snapshot", toJson id)]
  | .ok "describe" =>
      let s ← session.get
      return reply req
        [("status", Json.str "ok"),
         ("protocol", toJson Protocol.wireProtocol),
         ("lean", Json.str Lean.versionString),
         ("release", Json.str ReleaseInfo.version),
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
         ("protocol", toJson Worker.Protocol.wireProtocol),
         ("lean", Json.str Lean.versionString),
         ("release", Json.str Worker.ReleaseInfo.version),
         -- The client probes this pid between reply-read slices: a worker
         -- that dies under a still-live `lake env` wrapper is otherwise
         -- invisible to `proc.poll()` and would hang the read.
         ("pid", toJson (← IO.Process.getPID).toNat),
         ("snapshot", toJson (0 : Nat))]
      Worker.mainLoop ch queue session inflight
      return 0
