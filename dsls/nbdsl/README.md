# nbdsl — the reference DSL plugin

Categorical bookkeeping as a Lean-elaborated notebook language: checked
membership (`let X := t ∈ C`), transport conventions (`prefer`, `#home`,
`#via`), and predicates as category methods (`predicate`, `#methods`),
over all of mathlib.

This package is also the template for writing your own DSL plugin: it
`require`s the core by path and exposes one prelude module
(`NbDsl.Notebook`).

- Language reference & reducibility design: [../../docs/dsl.md](../../docs/dsl.md)
- Plugin contract: [../../docs/plugins.md](../../docs/plugins.md)
- Worked notebook: [../../dsl-notebooks/nbdsl-example.ipynb](../../dsl-notebooks/nbdsl-example.ipynb)
