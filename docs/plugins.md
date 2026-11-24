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

The core retains committed native environments, not replayable source:

- Committed mathematical state and observations belong to the environment.
  Pending transport identities, actual live owners and consumed rights
  belong to the resource supervisor and must not be rolled back.
- Plugins with external resources register the optional lifecycle in
  `Worker.Cell`. Prepare complete output and inert query descriptors
  during authorized execution; publish them with the native transaction
  only at the final commit gate. Abort must discard staged data.
- Long computations must support cooperative cancellation or report their
  actual unavailability. No automatic force, retry, source replay or
  cache restoration.
- Never touch control framing or invoke a provider, proof search or
  dynamic formatter from a query.

The core supplies explicit-parent execution, atomic publication, diagnostics,
and document staleness. Inspect/complete only consult committed descriptors
and native names; a query cannot run a predecessor.

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
| `--sandbox` | run the worker under bubblewrap: project + toolchain read-only, private `/tmp`, no network, dies with the kernel (env `NBDSL_SANDBOX=1`) |

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
