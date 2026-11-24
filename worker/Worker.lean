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
import Worker.Cell
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

/-- Only committed snapshots own native state and receipts. -/
structure Snapshot where
  id : Nat
  parent? : Option Nat
  cmdState : Lean.Elab.Command.State
  cellId : String
  requestId : Option String := none
  receipt : Option Cell.Receipt := none

structure Session where
  snapshots : Array Snapshot
  current : Nat
  nonce : String
  profile : Cell.Profile
  plugin : Option Cell.Plugin

private structure Pending where
  token : IO.CancelToken
  active : Option Cell.Active := none

/-- Nonrollbackable control metadata: claimed IDs and live/draining work, never
a completed payload or a recovery ledger. -/
private structure Controls where
  used : Std.HashSet String := {}
  pending : Std.HashMap String Pending := {}
  draining : Std.HashMap String Cell.Active := {}

private abbrev Gate := Std.Mutex Controls

private def obj (fields : List (String × Json)) := Json.mkObj fields

private def reply (nonce rid : String) (fields : List (String × Json)) : Json :=
  obj (("worker_nonce", toJson nonce) :: ("request_id", toJson rid) :: fields)

private def protocolError (nonce : String) (rid : Option String) (reason : String) : Json :=
  obj ([("op", Json.str "protocol_error"), ("worker_nonce", toJson nonce),
    ("reason", toJson reason)] ++ (rid.toList.map fun id => ("offending_request_id", toJson id)))

private def receiptJson (profile : Cell.Profile) (receipt : Cell.Receipt) : Json :=
  obj [("transaction_id", toJson receipt.transactionId),
    ("output_batch_id", toJson receipt.outputBatchId),
    ("profile_sha256", toJson profile.sha256),
    ("result_refs", toJson receipt.resultRefs)]

private def profileJson (profile : Cell.Profile) : Json :=
  obj [("id", toJson profile.id), ("sha256", toJson profile.sha256)]

private def serial? (req : Json) (field : String) : Option Nat := do
  let value ← (req.getObjValAs? String field).toOption
  let serial ← value.toNat?
  if toString serial == value then some serial else none

private def exactFields (req : Json) (names : Array String) : Bool :=
  match req with
  | .obj fields => fields.size == names.size && names.all (fun name => (fields.get? name).isSome)
  | _ => false

private def headerFields := #["op", "protocol", "worker_nonce", "request_id"]

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


private def visibleReceipt (session : Session) (snapshot : Nat) (target : String) :
    Option (Nat × Cell.Receipt) := Id.run do
  let mut next := some snapshot
  for _ in [:session.snapshots.size] do
    let some id := next | return none
    let some snap := session.snapshots[id]? | return none
    if snap.requestId == some target then
      if let some receipt := snap.receipt then return some (id, receipt)
    next := snap.parent?
  return none

private def committedReceipt (session : Session) (target : String) :
    Option (Nat × Cell.Receipt) := do
  let snap ← session.snapshots.find? (·.requestId == some target)
  return (snap.id, ← snap.receipt)

private def failedExecution (session : Session) (rid : String) (parent : Nat)
    (status : String) (reason : Option String := none) (diagnostics : Array Json := #[]) :
    Json :=
  reply session.nonce rid <| [("status", toJson status),
    ("snapshot", toJson (toString parent)), ("parent_snapshot", toJson (toString parent)),
    ("outputs", .arr #[]), ("diagnostics", .arr diagnostics)] ++
    reason.toList.flatMap (fun value => [("reason", toJson value), ("message", toJson value),
      ("stratum", "unavailable")])

private def finishPending (gate : Gate) (rid : String) (active : Option Cell.Active) :
    BaseIO Unit := do
  gate.atomically do
    let state ← get
    let mut draining := state.draining
    if let some handle := active then
      if ← handle.draining then draining := draining.insert rid handle
    set { state with pending := state.pending.erase rid, draining }

private def outputJson (batch : String) (index : Nat) (output : Output) : Json :=
  obj [("result_id", toJson s!"{batch}:{index}"), ("mime", obj output.data),
    ("metadata", output.metadata), ("display_id", output.displayId?.elim .null .str)]

private def validOutput (output : Output) : Bool :=
  match (output.data.find? (·.1 == "text/plain")).map (·.2) with
  | some (Json.str text) => !text.isEmpty
  | _ => false

private def execute (sessionRef : IO.Ref Session) (gate : Gate)
    (rid : String) (req : Json) : IO Json := do
  let session ← sessionRef.get
  let pending ← gate.atomically do return (← get).pending[rid]?
  let some pending := pending | return protocolError session.nonce (some rid) "missing_execute_claim"
  let names := headerFields ++ #["cell_id", "parent_snapshot", "session_policy", "code"]
  let some (code, cellId, parentId) := do
      if !exactFields req names || (req.getObjValAs? String "session_policy").toOption !=
          some sessionPolicy then none else do
        let code ← (req.getObjValAs? String "code").toOption
        let cellId ← (req.getObjValAs? String "cell_id").toOption
        let parent ← serial? req "parent_snapshot"
        some (code, cellId, parent)
    | do
      finishPending gate rid none
      return protocolError session.nonce (some rid) "invalid_execute"
  let some parent := session.snapshots[parentId]?
    | do
      finishPending gate rid none
      return failedExecution session rid parentId "error" (some "snapshot_unavailable")
  if ← pending.token.isSet then
    finishPending gate rid none
    return failedExecution session rid parentId "cancelled"
  let fileName := s!"<{cellId}>"
  let activeRef ← IO.mkRef (none : Option Cell.Active)
  try
    discard drainOutputs
    discard Cell.drainFailure
    let (active, initial) ← match session.plugin with
      | none => pure (none, parent.cmdState)
      | some plugin => do
        let (active, initial) ← Cell.run parent.cmdState fileName plugin.begin
        activeRef.set (some active)
        gate.atomically do
          let updated : Pending := { pending with active := some active }
          modify fun state => { state with pending := state.pending.insert rid updated }
        pure (some active, initial)
    if ← pending.token.isSet then
      if let some active := active then active.cancel
      return failedExecution session rid parentId "cancelled"
    let result ← Frontend.processCell initial code fileName (some pending.token)
    let outputs ← drainOutputs
    if ← pending.token.isSet then
      return failedExecution session rid parentId "cancelled"
    let diags ← result.messages.mapM diagnosticJson
    if result.messages.any (·.severity matches .error) || !outputs.all validOutput then
      if let some active := active then active.cancel
      let diagnostics := if outputs.all validOutput then diags.toArray else
        diags.toArray.push (obj [("severity", "error"), ("message", "invalid result MIME bundle"),
          ("start", obj [("line", toJson (1 : Nat)), ("column", toJson (0 : Nat))])])
      let failure ← Cell.drainFailure
      let response := failedExecution session rid parentId "error" none diagnostics
      return match failure with
        | none => response
        | some failure => (response.setObjVal! "stratum" (toJson failure.stratum)).setObjVal!
            "reason" (toJson failure.reason)
    -- The only commit/cancel linearization point. All source evaluation and
    -- output preparation above are outside the gate. The plugin's commit
    -- callback performs only the native transaction publication, never dispatch.
    gate.atomically do
      if ← pending.token.isSet then
        return failedExecution session rid parentId "cancelled"
      let id := session.snapshots.size
      let (receipt, cmdState) ← match active with
        | some handle => Cell.run result.cmdState fileName handle.commit
        | none => pure (⟨s!"{session.nonce}:transaction:{id}",
            s!"{session.nonce}:output:{id}", #[]⟩, result.cmdState)
      let snapshot : Snapshot := {
        id, parent? := some parentId, cmdState, cellId, requestId := some rid,
        receipt := some receipt }
      sessionRef.set { session with snapshots := session.snapshots.push snapshot, current := id }
      modify fun state => { state with pending := state.pending.erase rid }
      return reply session.nonce rid [
        ("status", "ok"), ("snapshot", toJson (toString id)),
        ("parent_snapshot", toJson (toString parentId)),
        ("commit", receiptJson session.profile receipt),
        ("diagnostics", .arr diags.toArray), ("sorries", .arr (result.sorries.map sorryJson)),
        ("outputs", .arr (outputs.mapIdx (outputJson receipt.outputBatchId)))]
  catch error =>
    if ← pending.token.isSet then
      return failedExecution session rid parentId "cancelled"
    let diagnostic := obj [("severity", "error"), ("message", toJson (toString error)),
      ("start", obj [("line", toJson (1 : Nat)), ("column", toJson (0 : Nat))])]
    return failedExecution session rid parentId "error" none #[diagnostic]
  finally
    discard drainOutputs
    discard Cell.drainFailure
    let active ← activeRef.get
    if let some active := active then active.cancel
    finishPending gate rid active

/-- Cancellation has an independent transport identity. Only the exact queued
or active target may be cancelled; a committed receipt cannot be undone. -/
private def cancel (sessionRef : IO.Ref Session) (gate : Gate)
    (rid : String) (req : Json) : IO Json := do
  let session ← sessionRef.get
  let names := headerFields ++ #["target_request_id", "mode"]
  let some (target, mode) := do
      if !exactFields req names then none else do
        let target ← (req.getObjValAs? String "target_request_id").toOption
        let mode ← (req.getObjValAs? String "mode").toOption
        if mode == "cooperative" || mode == "force" then some (target, mode) else none
    | return protocolError session.nonce (some rid) "invalid_cancel"
  let decision ← gate.atomically do
    let state ← get
    if let some pending := state.pending[target]? then
      pending.token.set
      return (some pending.active, none)
    if mode == "force" then
      if let some active := state.draining[target]? then
        return (some (some active), none)
    return (none, committedReceipt (← sessionRef.get) target)
  match decision with
  | (some active, _) =>
    if let some active := active then active.cancel
    if mode == "force" then
      let invalidated ← match active with | some active => active.force | none => pure #[]
      return reply session.nonce rid [("status", "forced"),
        ("invalidated_owners", toJson invalidated)]
    return reply session.nonce rid [("status", "cancelled")]
  | (_, some (id, receipt)) =>
    return reply session.nonce rid [("status", "already_committed"),
      ("snapshot", toJson (toString id)), ("commit", receiptJson session.profile receipt)]
  | _ => return reply session.nonce rid [("status", "not_found")]

/-- Queries consult data from the requested committed state. No candidate command
is parsed or elaborated. Syntax completeness uses only fixed token scanning. -/
private def query (session : Session) (rid op : String) (req : Json) : IO Json := do
  let names := headerFields ++ #["mode", "snapshot", "code"] ++
    (if op == "is_complete" then #[] else #["cursor"]) ++
    (if op == "inspect" then #["detail_level"] else #[])
  let mode := if op == "is_complete" then "syntax" else "environment"
  let some (id, code) := do
      if !exactFields req names || (req.getObjValAs? String "mode").toOption != some mode then none
      else do
        let id ← serial? req "snapshot"
        let code ← (req.getObjValAs? String "code").toOption
        some (id, code)
    | return protocolError session.nonce (some rid) "invalid_query"
  let some snapshot := session.snapshots[id]?
    | return reply session.nonce rid [("status", "unavailable"),
        ("reason", "snapshot_unavailable"), ("message", "snapshot_unavailable")]
  if op == "is_complete" then
    return reply session.nonce rid [("status", "ok"), ("result", "unknown")]
  let .ok cursor := req.getObjValAs? Nat "cursor"
    | return protocolError session.nonce (some rid) "invalid_cursor"
  if cursor > code.length then return protocolError session.nonce (some rid) "invalid_cursor"
  if op == "complete" then
    let (start, found) := Query.retainedCompletions snapshot.cmdState code cursor
    return reply session.nonce rid [("status", "ok"), ("matches", toJson found),
      ("cursor_start", toJson start), ("cursor_end", toJson cursor)]
  let .ok _ := req.getObjValAs? Nat "detail_level"
    | return protocolError session.nonce (some rid) "invalid_detail_level"
  match Query.inspect snapshot.cmdState code cursor with
  | none => return reply session.nonce rid [("status", "ok"), ("found", toJson false)]
  | some result => return reply session.nonce rid [("status", "ok"), ("found", toJson true),
      ("name", toJson result.name), ("type", toJson result.type), ("doc", toJson result.doc?)]

private def commitStatus (sessionRef : IO.Ref Session) (gate : Gate)
    (rid : String) (req : Json) : IO Json := do
  gate.atomically do
    let session ← sessionRef.get
    let some (snapshot, target) := do
        if !exactFields req (headerFields ++ #["snapshot", "target_request_id"]) then none
        else do
          let snapshot ← serial? req "snapshot"
          let target ← (req.getObjValAs? String "target_request_id").toOption
          some (snapshot, target)
      | return protocolError session.nonce (some rid) "invalid_commit_status"
    if session.snapshots[snapshot]?.isNone then
      return reply session.nonce rid [("status", "unavailable"), ("reason", "snapshot_unavailable")]
    if let some (id, receipt) := visibleReceipt session snapshot target then
      return reply session.nonce rid [("status", "committed"),
        ("snapshot", toJson (toString id)), ("commit", receiptJson session.profile receipt)]
    if (← get).pending.contains target then return reply session.nonce rid [("status", "pending")]
    return reply session.nonce rid [("status", "unavailable"), ("reason", "receipt_unavailable")]

private def handle (sessionRef : IO.Ref Session) (gate : Gate) (req : Json) : IO Json := do
  let session ← sessionRef.get
  let .ok rid := req.getObjValAs? String "request_id"
    | return protocolError session.nonce none "missing_request_id"
  match req.getObjValAs? String "op" with
  | .ok "execute" => execute sessionRef gate rid req
  | .ok op =>
    if #["inspect", "complete", "is_complete"].contains op then query session rid op req
    else if op == "describe" && exactFields req headerFields then
      return reply session.nonce rid [("status", "ok"), ("protocol", toJson wireProtocol),
        ("snapshot", toJson (toString session.current)), ("realization_profile", profileJson session.profile)]
    else return protocolError session.nonce (some rid) "unknown_operation"
  | .error _ => return protocolError session.nonce (some rid) "missing_operation"

private inductive Admission
  | rejected (diagnostic : Json)
  | accepted (rid : String)

private def admit (gate : Gate) (nonce : String) (req : Json) : BaseIO Admission := do
  let id := (req.getObjValAs? String "request_id").toOption
  unless (req.getObjValAs? Nat "protocol").toOption == some wireProtocol &&
      (req.getObjValAs? String "worker_nonce").toOption == some nonce do
    return .rejected (protocolError nonce id "incompatible_protocol")
  let some rid := id | return .rejected (protocolError nonce none "missing_request_id")
  if rid.isEmpty then return .rejected (protocolError nonce id "invalid_request_id")
  gate.atomically do
    let state ← get
    if state.used.contains rid then
      return .rejected (protocolError nonce (some rid) "duplicate_request_id")
    -- Claim the transport ID before validating operation-specific fields.
    let mut pending := state.pending
    if (req.getObjValAs? String "op").toOption == some "execute" then
      pending := pending.insert rid { token := ← IO.CancelToken.new }
    set { state with used := state.used.insert rid, pending }
    return .accepted rid

private partial def readerLoop (ch : Channel) (queue : Std.CloseableChannel.Sync Json)
    (session : IO.Ref Session) (gate : Gate) (nonce : String) : IO Unit := do
  let some req ← readFrame ch | return ()
  match ← admit gate nonce req with
  | .rejected diagnostic => writeFrame ch diagnostic
  | .accepted rid =>
    match req.getObjValAs? String "op" with
    | .ok "cancel" => writeFrame ch (← cancel session gate rid req)
    | .ok "commit_status" => writeFrame ch (← commitStatus session gate rid req)
    | .ok op =>
      if #["inspect", "complete", "is_complete"].contains op then
        writeFrame ch (← query (← session.get) rid op req)
      else
        if let .error _ ← (queue.send req).toBaseIO then return ()
    | .error _ => writeFrame ch (protocolError nonce (some rid) "missing_operation")
  readerLoop ch queue session gate nonce

private def readerTask (ch : Channel) (queue : Std.CloseableChannel.Sync Json)
    (session : IO.Ref Session) (gate : Gate) (nonce : String) : IO Unit := do
  try readerLoop ch queue session gate nonce
  finally discard (queue.close).toBaseIO

private partial def mainLoop (ch : Channel) (queue : Std.CloseableChannel.Sync Json)
    (session : IO.Ref Session) (gate : Gate) : IO Unit := do
  let some req ← queue.recv | return ()
  writeFrame ch (← handle session gate req)
  mainLoop ch queue session gate

private def defaultProfile : IO Cell.Profile := do
  let configuration := obj [("default", "all"), ("format", "cas-realization-profile/1"),
    ("id", "all"), ("rules", .arr #[])]
  let hash ← IO.Process.output { cmd := "sha256sum" } (some configuration.compress)
  unless hash.exitCode == 0 do throw (IO.userError "cannot establish startup profile")
  return ⟨"all", (hash.stdout.splitOn " ").head!⟩

/-- Import and initialize the selected prelude before announcing readiness. -/
unsafe def initSession (preludeModule : Lean.Name) : IO Session := do
  Lean.initSearchPath (← Lean.findSysroot)
  Lean.enableInitializersExecution
  let env ← Lean.importModules #[{ module := preludeModule }] {} (loadExts := true)
  let cmdState := Lean.Elab.Command.mkState env {} {}
  let cmdState := { cmdState with infoState.enabled := true }
  let plugin ← Cell.plugin?
  let ((profile, nonce), cmdState) ← match plugin with
    | some plugin => Cell.run cmdState "<startup>" plugin.startup
    | none =>
      let nonce := (← IO.FS.readFile "/proc/sys/kernel/random/uuid").trimAscii.toString
      pure ((← defaultProfile, nonce), cmdState)
  if nonce.isEmpty then throw (IO.userError "empty worker nonce")
  let initial : Snapshot := { id := 0, parent? := none, cmdState, cellId := "<prelude>" }
  return { snapshots := #[initial], current := 0, nonce, profile, plugin }

private partial def negotiate (ch : Channel) (nonce : String) : IO Bool := do
  let some req ← readFrame ch | return false
  let hello := obj [("op", "hello"), ("protocol", toJson wireProtocol),
    ("worker_nonce", toJson nonce), ("session_policy", toJson sessionPolicy)]
  if req == hello then
    writeFrame ch (obj [("op", "hello"), ("protocol", toJson wireProtocol),
      ("worker_nonce", toJson nonce), ("session_policy", toJson sessionPolicy), ("status", "ok")])
    return true
  if req == obj [("op", "shutdown")] then return false
  if req == obj [("op", "version")] then
    writeFrame ch (obj [("op", "version"), ("protocol", toJson wireProtocol)])
  else writeFrame ch (protocolError nonce none "incompatible_protocol")
  negotiate ch nonce

end Worker

unsafe def main (argv : List String) : IO UInt32 := do
  match Worker.parseWorkerArgs argv with
  | .error e =>
      IO.eprintln s!"nbdsl_worker: {e}"
      return 2
  | .ok args =>
      let ch ← openChannel args.reqFd args.repFd
      let initial ← Worker.initSession args.preludeModule
      let session ← IO.mkRef initial
      try
        writeFrame ch <| Json.mkObj [
          ("op", "ready"), ("protocol", toJson wireProtocol),
          ("lean", toJson Lean.versionString), ("release", toJson Worker.ReleaseInfo.version),
          ("pid", toJson (← IO.Process.getPID).toNat),
          ("worker_nonce", toJson initial.nonce), ("snapshot", "0"),
          ("realization_profile", Worker.profileJson initial.profile),
          ("features", toJson notebookFeatures)]
        unless ← Worker.negotiate ch initial.nonce do return 2
        let gate ← Std.Mutex.new ({} : Worker.Controls)
        let queue ← Std.CloseableChannel.Sync.new
        let _reader ← IO.asTask (Worker.readerTask ch queue session gate initial.nonce) .dedicated
        Worker.mainLoop ch queue session gate
        return 0
      finally
        if let some plugin := initial.plugin then
          let current ← session.get
          if let some snapshot := current.snapshots[current.current]? then
            discard <| Worker.Cell.run snapshot.cmdState "<shutdown>" plugin.close
