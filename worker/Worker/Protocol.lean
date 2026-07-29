/-
Framed-JSON control protocol for the nbdsl worker.

Frames are length-prefixed: the ASCII decimal byte-length of the UTF-8 JSON
payload, a newline, then the payload. Length-prefixing (rather than
newline-delimited JSON) means arbitrary user output can never be mistaken for
a protocol frame.

The control channel lives on dedicated file descriptors inherited from the
parent (Python passes their numbers via `--req-fd`/`--rep-fd` and keeps them
open across `lake env`'s exec). stdout/stderr are exclusively user streams:
`#eval IO.println` in a cell must not be able to corrupt control traffic.
-/
import Lean.Data.Json

namespace Worker.Protocol

open Lean (Json)

structure Channel where
  reqH : IO.FS.Handle
  repH : IO.FS.Handle

/--
Reopen the inherited pipe fds via `/dev/fd/N` (on Linux, `/proc/self/fd/N`).
`Mode.write` maps to `O_WRONLY|O_CREAT|O_TRUNC`; truncation is a no-op on
pipes, so reopening the write end this way is sound on Linux.
-/
def openChannel (reqFd repFd : Nat) : IO Channel := do
  let reqH ← IO.FS.Handle.mk s!"/dev/fd/{reqFd}" .read
  let repH ← IO.FS.Handle.mk s!"/dev/fd/{repFd}" .write
  return { reqH, repH }

def writeFrame (ch : Channel) (j : Json) : IO Unit := do
  let bytes := j.compress.toUTF8
  ch.repH.putStr s!"{bytes.size}\n"
  ch.repH.write bytes
  ch.repH.flush

private partial def readExact (h : IO.FS.Handle) (n : Nat)
    (acc : ByteArray := .empty) : IO ByteArray := do
  if acc.size ≥ n then
    return acc
  let chunk ← h.read (USize.ofNat (n - acc.size))
  if chunk.size == 0 then
    throw <| IO.userError "control channel: EOF mid-frame"
  readExact h n (acc ++ chunk)

/-- Read one frame; `none` on clean EOF (parent closed the request pipe). -/
def readFrame (ch : Channel) : IO (Option Json) := do
  let line ← ch.reqH.getLine
  if line.isEmpty then
    return none
  let some n := line.trimAscii.toNat?
    | throw <| IO.userError s!"control channel: bad frame length {repr line}"
  let bytes ← readExact ch.reqH n
  let some payload := String.fromUTF8? bytes
    | throw <| IO.userError "control channel: frame is not UTF-8"
  match Json.parse payload with
  | .ok j => return some j
  | .error e => throw <| IO.userError s!"control channel: bad JSON frame: {e}"

end Worker.Protocol
