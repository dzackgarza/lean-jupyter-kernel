# Bring your own DSL — the plugin contract

The notebook core is DSL-agnostic and the boundary is enforced: the QC gate
fails if anything under `worker/` imports a DSL module. A DSL is a plugin,
and **the entire plugin manifest is one Lean module name** — everything a
DSL is flows through what importing its prelude does to the environment.

## What a plugin provides

1. **A Lake package** that `require`s the core package `«nbdsl-worker»`
   (path or git) — for exactly one library, `Worker`. The only legal import
   today is `Worker.Output`; nothing under `Worker.*` may be shadowed or
   extended.
2. **One prelude module** — the entry point. Importing it must bring: the
   surface syntax and command elaborators, the semantic state (as
   persistent env extensions), the standard library, and docstrings.
3. *(Optional)* rich outputs via `Worker.emitOutput`, with namespaced MIME
   types (`application/vnd.<dsl>.<kind>+json`) always alongside
   `text/plain`.
4. *(Optional, the only non-Lean part)* frontend cosmetics: a MIME renderer
   plugin and highlighter keywords (JupyterLab setting `dslKeywords` on
   `jupyterlab_nbdsl:language`; new `#commands` highlight automatically).

## The plugin laws

The invariants the core silently relies on:

- **All semantic state lives in the `Environment`** (persistent env
  extensions), never in module-level `IO.Ref`s. This is the load-bearing
  law: snapshots, cell atomicity/rollback, restart replay, the olean
  session cache, and staleness all derive from it — and all silently break
  without it. (The output sink is exempt: it is rendering, request-local,
  and core-owned.)
- **Commands are deterministically replayable** — replaying the committed
  cell sources must reconstruct the same state (the restart invariant).
- Long computations should pass elaboration checkpoints so cooperative
  cancellation works; pure interpreted loops fall back to kill+replay.
- Never touch stdout framing or the control fds.

The payoff: obey the state law and the core provides cell atomicity,
document-order semantics, sorry tracking, staleness marking, session
caching, and crash recovery — with zero plugin code. Completion and
inspection resolve Lean-environment names (declarations, opens, namespaces).
Extension-backed registrations are visible through ordinary execution and
rich output; a dedicated plugin query contract for completion/inspection is
future work.

## Reducibility

If your DSL wants `decide`-style checking on declared objects, keep the
carrier-reduction chain reducible end to end — see
[dsl.md → The reducibility chain](dsl.md#the-reducibility-chain-why-decide-works-on-declared-objects).
This is a per-DSL design choice, not a core requirement.

## Installing a plugin kernel

```bash
# in your DSL package: build the worker (resolved from the dependency tree)
lake build nbdsl_worker && lake exe cache get   # if you use mathlib
lake build YourDsl

python -m nbdsl_kernel.install \
  --project /path/to/your-dsl-package \
  --prelude-module Your.Prelude \
  --name yourdsl --display-name "YourDsl (Lean 4)" \
  [--init-cell "set_option ... "] [--sandbox]
```

Kernelspec knobs (all in `nbdsl_kernel/nbdsl_kernel/install.py`):

| Flag | Effect |
| --- | --- |
| `--project` | Lake project the worker runs in (cwd; elan resolves its pinned toolchain) |
| `--prelude-module` | the plugin manifest (env `NBDSL_PRELUDE`) |
| `--name` / `--display-name` | kernelspec identity |
| `--init-cell` | commands run once after worker start, becoming the session's base snapshot — the only way to set `set_option` defaults (they don't cross module import). Failure is loud, per execute. |
| `--sandbox` | run the worker under bubblewrap: project + toolchain read-only, private `/tmp`, no network, dies with the kernel (env `NBDSL_SANDBOX=1`; disables the session cache) |

The worker binary is resolved from the project's own build tree, a git
dependency under `.lake/packages/`, or a path dependency at the directory
the Lake manifest records — so a downstream package never copies the exe.

## Constraints to know

- **Toolchain binding**: the worker executable and the DSL's oleans must
  come from the same Lean toolchain (olean compatibility). The worker is a
  library your project builds, not a system-wide binary; per-toolchain, one
  build serves all DSL packages on that toolchain.
- One kernel session speaks one prelude. Different DSLs = different
  kernelspecs; they can share the worker build.
