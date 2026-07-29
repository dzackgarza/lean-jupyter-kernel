/-
Session cache: snapshot persistence as an olean, used by the kernel to make
worker restarts cheap without replaying the committed cell ledger.

Design: the committed environment is written with `Lean.writeModule` — the
same serializer the compiler uses for oleans — so constants AND persistent
env-extension entries (a DSL's registry state) round-trip with full fidelity.
Loading is an ordinary `importModules` of the cache module. The scope stack
is serialized separately as JSON.

Honest ceilings (callers fall back to source replay on `.error`):
- only single-scope states are cacheable (a dangling `namespace`/`section`
  or `variable` declarations refuse to save — their state includes syntax);
- options limited to primitive values (no syntax-valued options);
- the cache is toolchain-bound like any olean; the kernel keys it by
  toolchain + prelude + ledger hash and treats load failure as a miss.
-/
import Lean

namespace Worker.SessionCache

open Lean

def cacheModule : Name := `NbdslSessionCache

private def dataValueToJson : DataValue → Except String Json
  | .ofString s => .ok <| Json.mkObj [("k", "string"), ("v", Json.str s)]
  | .ofBool b => .ok <| Json.mkObj [("k", "bool"), ("v", Json.bool b)]
  | .ofName n => .ok <| Json.mkObj [("k", "name"), ("v", Json.str n.toString)]
  | .ofNat n => .ok <| Json.mkObj [("k", "nat"), ("v", toJson n)]
  | .ofInt i => .ok <| Json.mkObj [("k", "int"), ("v", toJson i)]
  | .ofSyntax _ => .error "syntax-valued option"

private def dataValueOfJson (j : Json) : Except String DataValue := do
  let k ← j.getObjValAs? String "k"
  match k with
  | "string" => return .ofString (← j.getObjValAs? String "v")
  | "bool" => return .ofBool (← j.getObjValAs? Bool "v")
  | "name" => return .ofName (← j.getObjValAs? String "v").toName
  | "nat" => return .ofNat (← j.getObjValAs? Nat "v")
  | "int" => return .ofInt (← j.getObjValAs? Int "v")
  | _ => .error s!"unknown option kind {k}"

private def openDeclToJson : OpenDecl → Json
  | .simple ns ex =>
      Json.mkObj [("simple", Json.str ns.toString),
                  ("except", Json.arr (ex.map (Json.str ·.toString)).toArray)]
  | .explicit id decl =>
      Json.mkObj [("id", Json.str id.toString),
                  ("decl", Json.str decl.toString)]

private def openDeclOfJson (j : Json) : Except String OpenDecl := do
  if let .ok ns := j.getObjValAs? String "simple" then
    let ex := (j.getObjValAs? (Array String) "except").toOption.getD #[]
    return .simple ns.toName (ex.map (·.toName)).toList
  let id ← j.getObjValAs? String "id"
  let decl ← j.getObjValAs? String "decl"
  return .explicit id.toName decl.toName

private def scopeToJson (sc : Elab.Command.Scope) : Except String Json := do
  unless sc.varDecls.isEmpty do
    .error "variable declarations in scope"
  let mut opts := #[]
  for (name, v) in sc.opts do
    opts := opts.push <| Json.mkObj [("name", Json.str name.toString),
                                     ("value", ← dataValueToJson v)]
  return Json.mkObj
    [("currNamespace", Json.str sc.currNamespace.toString),
     ("openDecls", Json.arr (sc.openDecls.map openDeclToJson).toArray),
     ("levelNames", Json.arr (sc.levelNames.map (Json.str ·.toString)).toArray),
     ("opts", Json.arr opts)]

private def scopeOfJson (j : Json) : Except String Elab.Command.Scope := do
  let mut opts : Options := {}
  for o in ← j.getObjValAs? (Array Json) "opts" do
    let name ← o.getObjValAs? String "name"
    let v ← dataValueOfJson (← o.getObjVal? "value")
    opts := opts.insert name.toName v
  let openDecls ← (← j.getObjValAs? (Array Json) "openDecls").mapM openDeclOfJson
  let levelNames := (← j.getObjValAs? (Array String) "levelNames").map (·.toName)
  return { header := ""
           opts
           currNamespace := (← j.getObjValAs? String "currNamespace").toName
           openDecls := openDecls.toList
           levelNames := levelNames.toList }

/-- Persist the state's environment (olean) and scope (json) under `dir`. -/
def save (cmdState : Elab.Command.State) (dir : System.FilePath)
    : IO (Except String Unit) := do
  let [sc] := cmdState.scopes
    | return .error "open namespace/section scopes — replay instead"
  match scopeToJson sc with
  | .error e => return .error e
  | .ok scJson =>
      IO.FS.createDirAll dir
      let env := cmdState.env.setMainModule cacheModule
      Lean.writeModule env (dir / s!"{cacheModule}.olean")
      IO.FS.writeFile (dir / "scope.json") scJson.compress
      return .ok ()

/-- Rebuild a `Command.State` from `save`'s output. Throws on any problem —
the caller treats that as a cache miss. -/
unsafe def loadUnsafe (dir : System.FilePath) : IO Elab.Command.State := do
  let scText ← IO.FS.readFile (dir / "scope.json")
  let sc ← match Json.parse scText >>= scopeOfJson with
    | .ok sc => pure sc
    | .error e => throw <| IO.userError s!"session cache scope: {e}"
  searchPathRef.modify (dir :: ·)
  -- `withImporting` (inside importModules) resets the initializer-execution
  -- flag on every import, so it must be re-enabled for each one.
  enableInitializersExecution
  let env ← importModules #[{ module := cacheModule }] {} (loadExts := true)
  let st := Elab.Command.mkState env {} sc.opts
  return { st with scopes := [sc], infoState.enabled := true }

@[implemented_by loadUnsafe]
def load (dir : System.FilePath) : IO Elab.Command.State :=
  throw <| IO.userError "unreachable: implemented_by loadUnsafe"

end Worker.SessionCache
