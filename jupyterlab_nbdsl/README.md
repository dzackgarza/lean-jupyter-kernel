# jupyterlab_nbdsl

JupyterLab 4 federated extension, four plugins:

- `jupyterlab_nbdsl:language` — CodeMirror 6 highlighting for
  `text/x-lean4` (generic nbdsl surface); extra DSL keywords via the
  `dslKeywords` setting.
- `jupyterlab_nbdsl:casdsl-language` — CodeMirror 6 highlighting for
  `text/x-casdsl`, the lean-cas-dsl surface grammar (its own reserved words,
  domains, relations and operators — not Lean 4; the word lists mirror
  `CasDsl/Syntax.lean`).
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
