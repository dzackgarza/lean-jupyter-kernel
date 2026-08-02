# Architecture

The system is three processes and one invariant.

```text
JupyterLab / jupyter console / any Jupyter client
        │  Jupyter kernel protocol (ZMQ)
        ▼
nbdsl_kernel      Python ipykernel wrapper — transport and rendering ONLY
        │  length-prefixed JSON frames on dedicated inherited fds
        ▼
nbdsl_worker      persistent Lean executable — parsing, elaboration,
        │         semantic state, proof checking
        ▼
DSL prelude       ordinary Lean library (command elaborators + env
                  extensions), imported once at worker start
```

**The invariant**: cell text reaches Lean verbatim. Python never tokenizes,
parses, or interprets a character of it. Everything semantic — including
completion, hover, and completeness — is *asked of* the worker, never
computed beside it.

## The worker (`worker/`, Lake package `nbdsl-worker`)

Mathlib-free; builds in seconds. Modules:

- **`Worker/Protocol.lean`** — the framed-JSON control channel. Frames are
  `<byte-length>\n<json>` on two dedicated file descriptors passed by the
  parent (`--req-fd`/`--rep-fd`, reopened via `/dev/fd/N`). User code can
  print anything to stdout without corrupting control traffic (and `#eval`
  output is additionally captured by Lean into the message log, arriving as
  info diagnostics).
- **`Worker/Frontend.lean`** — per-cell elaboration, reimplementing the
  core-frontend pattern (`Parser.parseCommand` +
  `Command.elabCommandTopLevel`) with three deliberate deviations:
  - the end-of-input terminal command is never elaborated, so scopes a cell
    leaves open (a dangling `namespace`/`section`) persist into later cells;
  - internal elaboration exceptions become error diagnostics instead of
    killing the worker;
  - messages **and info trees are accumulated across the commands of a
    cell** — `elabCommandTopLevel` resets both per command (modern Lean
    reports them via snapshot machinery), so without explicit accumulation
    only the last command's diagnostics and sorries survive a cell.
- **`Worker.lean`** — session state and the op dispatcher.
  - *Snapshots*: every committed cell retains its full
    `Elab.Command.State` (environment, scopes, opens, options, name
    generators) in an in-memory DAG keyed by parent. `Command.State` is a
    persistent pure value; retaining it **is** the snapshot mechanism.
    Snapshots are never garbage-collected (POC ceiling).
  - *Atomicity*: a cell elaborates against a copy of its parent state; the
    candidate commits as a new snapshot only if no diagnostic has error
    severity. A failed cell leaves committed state — including DSL registry
    entries — identical to its parent.
  - *Reader task + cancellation*: a dedicated task is the sole reader of
    the request fd, queueing ordinary requests (`Std.CloseableChannel`) and
    handling `cancel` frames out-of-band by setting the in-flight
    `IO.CancelToken`, which `Frontend` passes into `Command.Context`.
    Elaboration then aborts at its next checkpoint (the same mechanism the
    language server uses; ~0.2 s for tactic proofs) and the execute replies
    `status:"cancelled"` with no commit. The reader closes its queue in a
    `finally` — a reader death without that closes left workers orphaned
    (observed; see git history).
  - *Session cache*: `save_session` writes the committed environment with
    `Lean.writeModule` — the compiler's own olean serializer, so constants
    **and persistent env-extension entries** (DSL registries) round-trip —
    plus the scope stack as JSON. `load_session` re-imports it as a module.
    Honest refusals fall back to source replay: open `namespace`/`section`
    scopes, `variable` declarations, syntax-valued options. Gotcha encoded
    in `SessionCache.loadUnsafe`: `withImporting` resets the
    initializer-execution flag on *every* import, so it must be re-enabled
    before each `importModules (loadExts := true)`.
- **`Worker/Query.lean`** — identifier services against the current
  snapshot: type-aware dot completion (resolve the head, `whnf` its type,
  offer members of the head constant), open-aware prefix completion over
  the environment, and inspect resolution. Hover goes further: the
  `inspect` op elaborates the cell as *pure analysis* (candidate state
  discarded, output sink drained) and answers from the info trees via
  `Info.fmtHover?` — server-grade hover including locals. Like the language
  server, analysis executes elaboration, so `#eval` side effects run.
- **`Worker/Output.lean`** — the output sink, the single API a DSL may call
  (`Worker.emitOutput`): request-local MIME bundles the kernel republishes.
  Rendering, never semantics — nothing here enters the environment.

Process discipline: the worker runs in its **own session**
(`start_new_session`) so Jupyter's interrupt SIGINT reaches only the
kernel. The client captures `lake env` then spawns `nbdsl_worker` as the
owned child, so `proc.pid` is the worker (except under Bubblewrap, where
host PID ownership is resolved from the process tree). Killing uses
`killpg` on that group.

## The kernel adapter (`nbdsl_kernel/`)

`kernel.py` is a thin `ipykernel` wrapper; `worker.py` owns everything
fd-shaped; `protocol.py` models the wire protocol in Pydantic — raw frames
become typed models inside `WorkerClient`, a malformed worker reply is a
`ValidationError` crash, and `dict[str, Any]` does not circulate
(ipykernel's inbound comm payloads are likewise ingested to models at the
handler boundary).

Two execution modes:

- **REPL mode** (no frontend extension, e.g. `jupyter console`): parent =
  the client's current snapshot; committed cells join a replay ledger.
- **Document mode** (JupyterLab with `jupyterlab_nbdsl`): the frontend
  streams `{type:"document", cells:[{id,source}]}` over the
  `nbdsl_document` comm on load, cell-list/text changes (`sharedModel`
  subscription — list-change signals miss typing), and before each
  scheduled execution. Executing cell *i* first re-establishes the
  invariant *"cell i's snapshot equals elaborating the visible prefix
  through i"*: unchanged prefix cells reuse cached snapshots, edited or
  moved ones re-run (visible `↻` notes), an upstream failure aborts with
  `UpstreamError`. After each execution/document change the kernel
  broadcasts `{type:"status", fresh, stale}` back on the comm; the
  extension marks stale cells.

Recovery matrix on worker death (normally interrupt escalation):

| Mode | Recovery |
| --- | --- |
| REPL, cache key matches ledger | `load_session` (olean restore) |
| REPL, cache invalid/uncacheable | source replay of the ledger |
| Document | fresh worker; prefix revalidation rebuilds on demand |

The kernelspec init cell (`install.py --init-cell` → `NBDSL_INIT`) runs
once after worker start and becomes the session's base snapshot — the only
way to set session defaults a prelude cannot (`set_option` does not cross
module import). A failing init cell fails every execute loudly.

## The JupyterLab extension (`jupyterlab_nbdsl/`)

Three plugins, all DSL-agnostic:

- `jupyterlab_nbdsl:language` — CodeMirror 6 StreamLanguage for
  `text/x-lean4`; extra DSL keywords come from JupyterLab settings
  (`dslKeywords`, default `["prefer"]`).
- `jupyterlab_nbdsl:document` — the document/staleness comm described
  above.
- `jupyterlab_nbdsl:path-renderer` — renders
  `application/vnd.nbdsl.path+json` bundles as a badge-and-arrows chain.

Shared modules (`@jupyterlab/*`, `@codemirror/language`, `@lezer/highlight`)
are consumed as core singletons; nothing is bundled twice.
