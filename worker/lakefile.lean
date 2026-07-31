import Lake
open Lake DSL System

/-
The notebook core: framed protocol, per-cell elaboration, snapshot DAG,
cancellation, and the output sink. Deliberately mathlib-free — it builds in
seconds and is the stable dependency surface for DSL plugin packages
(`require «nbdsl-worker» from git/path`, import `Worker.Output`, nothing
else). The QC gate rejects any `import NbDsl` under Worker sources.
-/
package «nbdsl-worker» where
  version := v!"1.1.0"

/--
The worker's exact build identity, as the single line
`<40-hex commit> clean|dirty`, embedded into the binary by the tracked
`Worker.BuildCommit` module via `include_str`.

`git -C <package dir>` rather than an assumed cwd, so this is correct in this
repository, in a fresh clone, and in a consumer's `.lake/packages/<pkg>`
checkout where the package root is a *subdirectory* of the clone. Missing git
identity is a hard build failure: a worker that cannot say what it was built
from must not exist. A dirty tree is recorded and still builds.

`include_str` is invisible to Lake's change detection (Lake reads no such
dependency; `lake build` would happily keep a stale `.olean`), so the artifact
reaches the compiler only through the `needs` fields below: this target's
trace is mixed into the library's dep trace, which is what makes a later
commit recompile the module that embeds it. Coarse — it invalidates the whole
mathlib-free `Worker` library, which builds in seconds.
-/
target buildCommit pkg : FilePath := Job.async do
  let git (args : Array String) : JobM String := do
    let out ← IO.Process.output
      { cmd := "git", args := #["-C", pkg.dir.toString] ++ args }
    if out.exitCode != 0 then
      error s!"nbdsl-worker: `git {" ".intercalate args.toList}` failed in \
        {pkg.dir} (exit {out.exitCode}): {out.stderr}"
    return out.stdout
  let commit := (← git #["rev-parse", "HEAD"]).trimAsciiEnd.copy
  let status := (← git #["status", "--porcelain"]).trimAsciiEnd.copy
  let stamp := s!"{commit} {if status.isEmpty then "clean" else "dirty"}"
  addPureTrace stamp "build-commit"
  let path := pkg.buildDir / "build-commit.txt"
  buildFileUnlessUpToDate' (text := true) path do
    createParentDirs path
    IO.FS.writeFile path stamp
  return path

@[default_target]
lean_lib Worker where
  needs := #[`@/buildCommit]

/--
The persistent notebook worker. `supportInterpreter` is required because
cells are elaborated (and `#eval`'d) at runtime against the imported
`.olean`s, so the executable must expose Lean's symbols to interpreted code.
-/
lean_exe nbdsl_worker where
  root := `Worker
  supportInterpreter := true
  needs := #[`@/buildCommit]
