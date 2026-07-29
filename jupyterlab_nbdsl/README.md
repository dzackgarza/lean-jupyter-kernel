# jupyterlab_nbdsl

JupyterLab 4 federated extension, three DSL-agnostic plugins:

- `jupyterlab_nbdsl:language` — CodeMirror 6 highlighting for
  `text/x-lean4`; extra DSL keywords via the `dslKeywords` setting.
- `jupyterlab_nbdsl:document` — streams notebook cell order/sources to the
  kernel over the `nbdsl_document` comm (document-order semantics) and
  applies the kernel's fresh/stale broadcast as the `nbdsl-stale` cell
  class.
- `jupyterlab_nbdsl:path-renderer` — renders
  `application/vnd.nbdsl.path+json` bundles.

Develop: `jlpm install && jlpm test && jlpm build` (venv `bin` on `PATH`;
the `labextension develop` symlink makes builds live on reload). Pure logic
is node-tested; comm wiring is covered by the Python E2E suite driving the
same messages.

- Comm payloads & semantics: [../docs/architecture.md](../docs/architecture.md)
