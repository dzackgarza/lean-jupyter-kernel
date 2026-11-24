/-
Generic cell lifecycle, owned by the notebook worker. The DSL supplies its
transaction through the public hook at startup; no Worker module imports it.
Only immutable observations enter committed Environment snapshots.
-/
import Lean
import Std.Sync.Mutex
import Worker.Output

namespace Worker.Cell

open Lean Elab Command

structure Profile where
  id : String
  sha256 : String

structure Receipt where
  transactionId : String
  outputBatchId : String
  resultRefs : Array String

structure Observation where
  name : String
  type : String
  doc : Option String := none

private initialize observations : EnvExtension (Array Observation) ←
  registerEnvExtension (pure #[])

/-- The owning implementation prepares these strings during authorized execution. -/
def setObservations (entries : Array Observation) : CoreM Unit :=
  modifyEnv (observations.setState · entries)

/-- Inert lookup reads only the committed extension. -/
def getObservations (env : Environment) : Array Observation :=
  observations.getState env

/-- Request-local error metadata, never a cache or a mathematical result.
A DSL can preserve its original failure classification at the outer cell
boundary without inspecting printed diagnostic strings. -/
structure Failure where
  stratum : Option String
  reason : String

private initialize failureSink : IO.Ref (Option Failure) ← IO.mkRef none

def reportFailure (failure : Failure) : IO Unit :=
  failureSink.set (some failure)

def drainFailure : IO (Option Failure) :=
  failureSink.modifyGet fun failure => (failure, none)

/-- The callbacks retain only an active transaction. After settlement, the owning
implementation must drop its staged payloads; its resource cleanup may still drain. -/
structure Active where
  commit : Array Worker.Output → CommandElabM Receipt
  cancel : BaseIO Unit
  force : IO (Array String)
  draining : BaseIO Bool

structure Plugin where
  startup : CommandElabM (Profile × String)
  begin : CommandElabM Active
  close : CommandElabM Unit

-- A process has one selected prelude and one lifecycle implementation, registered
-- by that prelude. No semantic state or completed results live in this registry.
private initialize registered : IO.Ref (Option Plugin) ← IO.mkRef none

def register (plugin : Plugin) : IO Unit := do
  if (← registered.get).isSome then
    throw (IO.userError "more than one notebook cell lifecycle was registered")
  registered.set (some plugin)

def plugin? : IO (Option Plugin) := registered.get

/-- Run a lifecycle command in the same native candidate Environment as the cell.
It is not a user-source elaboration or a second evaluation of any expression. -/
def run (state : Command.State) (fileName : String) (action : CommandElabM α) :
    IO (α × Command.State) := do
  let context : Command.Context := {
    cmdPos := 0, fileName, fileMap := FileMap.ofString "", snap? := none, cancelTk? := none }
  match ← EIO.toIO' ((action context).run state) with
  | .ok result => return result
  | .error error => throw (IO.userError (← error.toMessageData.toString))

end Worker.Cell
