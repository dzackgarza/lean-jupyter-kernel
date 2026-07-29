/-
Structured notebook output — CORE infrastructure, not DSL code.

This module is the stable surface a DSL package depends on to emit rich
outputs; the dependency arrow is DSL → Worker, never the reverse. Nothing
under `Worker.*` may import DSL modules, so a replacement DSL is a new Lean
package requiring this library plus a `--prelude-module` change — zero edits
to the worker, kernel, or frontend extension.

Outputs are MIME bundles the Jupyter kernel republishes as `display_data` /
`execute_result`. They are *rendering*, not semantics: the sink is a
request-local `IO.Ref` the worker clears before and drains after each cell,
and nothing here ever enters the `Environment` or `Command.State`.
-/
import Lean

namespace Worker

open Lean (Json)

structure Output where
  /-- MIME bundle: `(mime type, payload)`. Always include `text/plain`. -/
  data : List (String × Json)
  metadata : Json := Json.mkObj []
  displayId? : Option String := none

initialize outputSink : IO.Ref (Array Output) ← IO.mkRef #[]

def emitOutput (o : Output) : IO Unit :=
  outputSink.modify (·.push o)

def drainOutputs : IO (Array Output) :=
  outputSink.modifyGet fun os => (os, #[])

def Output.toJson (o : Output) : Json :=
  Json.mkObj
    [("data", Json.mkObj o.data),
     ("metadata", o.metadata),
     ("display_id", o.displayId?.elim Json.null Json.str)]

end Worker
