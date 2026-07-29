# Deployment

## Local development (this repo's `.venv`)

```bash
just cache && just build
uv venv .venv && uv pip install -p .venv/bin/python -e 'nbdsl_kernel[test]' -e jupyterlab_nbdsl
.venv/bin/python -m nbdsl_kernel.install --project "$PWD/dsls/nbdsl"
PATH="$PWD/.venv/bin:$PATH" .venv/bin/jupyter labextension develop --overwrite jupyterlab_nbdsl
jupyter lab dsl-notebooks/nbdsl-example.ipynb   # kernel: "NbDsl (Lean 4)"
```

`labextension develop` symlinks the build output, so `jlpm build` in
`jupyterlab_nbdsl/` is live on browser reload. It shells out to
`jupyter-builder`, so the venv's `bin` must be on `PATH`.

## Installing into a running Jupyter service (editable)

The goal: DSL updates propagate to live notebooks with no reinstall step —
Python/extension changes on kernel restart / browser reload, Lean changes
after `lake build` + kernel restart.

Worked example against a systemd-user JupyterLab service (here the Sage
venv service on port 8888; substitute your service's python):

```bash
SVCPY=/path/to/service-venv/bin/python

# 1. editable-install the kernel package and the Lab extension
uv pip install -p $SVCPY -e nbdsl_kernel -e jupyterlab_nbdsl

# 2. kernelspec (argv records $SVCPY; --project points at this repo)
$SVCPY -m nbdsl_kernel.install --project /path/to/repo/dsls/nbdsl

# 3. labextension as a symlink into the service venv's share dir
PATH="$(dirname $SVCPY):$PATH" \
  $SVCPY -m jupyter labextension develop --overwrite /path/to/repo/jupyterlab_nbdsl

# 4. restart the service
systemctl --user restart your-jupyter.service
```

Verify through the live server:

```bash
curl -s http://localhost:8888/api/kernelspecs | python3 -c \
  "import sys,json; print(sorted(json.load(sys.stdin)['kernelspecs']))"
```

Notebooks that live in the repo can be surfaced in the service's root via a
symlink (this repo keeps `dsl-notebooks/`, symlinked into the research
notebooks tree).

## Operational characteristics

- **Worker startup**: the prelude imports **all of mathlib**
  (`sage.all`-style); expect tens of seconds cold, faster warm, and a
  multi-GB worker RSS. Budget memory per concurrent kernel.
- **Interrupt**: cooperative cancel (~0.2 s) when elaboration passes
  checkpoints; otherwise kill + recovery (session cache or replay in REPL
  mode, prefix revalidation in document mode).
- **The session cache** lives in a per-kernel tempdir, is keyed by
  prelude + ledger, and is disabled in sandbox mode (the sandboxed worker
  cannot write outside its private tmpfs).
- **Sandbox mode** (`--sandbox`): bubblewrap allowlist — project and
  toolchain read-only, private `/tmp`, no network, no foreign pids,
  `--die-with-parent`. A process boundary is not a security sandbox; this
  OS-level isolation is what makes untrusted notebooks tolerable. Verify
  with `nbdsl_kernel/tests/sandbox_check.py` (requires bwrap; fails loudly
  without it).
- **Disk**: the DSL package's `.lake` (mathlib checkout + oleans) runs
  ~7–8 GB; worker imports thrash badly on a full disk (observed: stalled
  `filemap_fault` page faults at 100% disk) — keep headroom.

## Driving the service programmatically

Any Jupyter client works (REST + kernel websocket). If the
jupyter-assistant-api adapter fronts your server, its `japi` launcher
drives notebooks by command (`use-notebook kernel_name:nbdsl ...`,
`execute-cell`, `read-cell`, `unuse-notebook`) — note `unuse-notebook`
unbinds without shutting the kernel down (keep-warm design); delete the
kernel explicitly to reclaim its memory.
