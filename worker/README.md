# nbdsl-worker

The notebook core: a persistent Lean executable owning parsing,
elaboration, snapshots, cancellation, the session cache, query services,
and the output sink. Mathlib-free — builds in seconds — and the stable
dependency surface for DSL plugin packages (`require «nbdsl-worker»`,
import `Worker.Output`, nothing else).

Hard boundary, enforced by the QC gate: nothing here imports DSL modules.

- Internals: [../docs/architecture.md](../docs/architecture.md)
- Wire protocol: [../docs/protocol.md](../docs/protocol.md)
- Plugin contract: [../docs/plugins.md](../docs/plugins.md)
