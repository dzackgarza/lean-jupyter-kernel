# Research: Worker protocol 2 and the notebook client

Each entry states a decision, its source and its reason.

## R1. A missing parent is `status: "unavailable"`

**Decision**: `execute` on a parent that the worker does not hold replies
`{"status":"unavailable","reason":"snapshot_unavailable","snapshot":<parent>,"parent_snapshot":<parent>,"outputs":[],"diagnostics":[]}`.
**Source**: [NS] §3.1 ("Missing parent gives `unavailable/snapshot_unavailable`") and §5 (row
"unavailable worker/snapshot"). **Reason**: the local branch replies `status:"error"` with
`stratum:"unavailable"`, which the client cannot tell from a cell error.

## R2. Unknown operations are protocol errors

**Decision**: an unknown `op`, mode or control field after the handshake receives
`protocol_error` with reason `unknown_operation` or `invalid_<op>`. The `unsupported` reply of
protocol 1 (`docs/protocol.md:30-31` on `main`) is removed. **Source**: [NS] §2 and §3.2
("Malformed/unknown controls are protocol errors").

## R3. The drain report is a field of the cell status

**Decision**: `Worker.Cell.Active` exposes `drainReport : BaseIO DrainReport` in place of
`draining : BaseIO Bool`. `DrainReport` is `drained`, `draining` or
`cleanup_unacknowledged` with the list of failures. `commit_status` and a cooperative `cancel`
reply carry `"drain": {"state": …, "failures": […]}` for a target that is cancelled or draining.
The plugin supplies the value; for the CAS it is `CellTransaction.draining` and
`FramedConnection.cleanupFailures` of lean-cas-dsl. **Source**: lean-cas-dsl `tasks.md`,
"Unreached code", row T089 ("The worker carries the report in the cell status (T091)").

## R4. The client always names the parent

**Decision**: the kernel adapter computes the parent for every execution: the cell metadata
parent when present, else the document parent, else the snapshot of the last committed
execution of this session. The client method `execute` without a parent is removed; only
`execute_at(code, cell_id, parent)` exists. **Source**: [NS] §1 ("explicit executions queue
with their selected parents") and §3.1.

## R5. Application log location and form

**Decision**: the worker takes `--log-file PATH` and writes one JSON object per line. The client
passes `<jupyter runtime dir>/nbdsl-<kernel id>.worker.jsonl` and writes its own records to
`<jupyter runtime dir>/nbdsl-<kernel id>.client.jsonl`. Tests pass a path under the run
directory of `records/test-runs/`. A record holds `time`, `request_id`, `op`, `cell_id`,
`parent_snapshot`, `transaction_id`, `status`, `snapshot`, `output_batch_id`, `elapsed_ms` and,
for a failure, `reason`. Nothing of the log reaches the notebook. **Source**: [KS] FR-043;
constitution E6 and J7.

## R6. Test-run logs and timing records

**Decision**: a pytest plugin in `nbdsl_kernel/tests/conftest.py` and the roundtrip driver
write `records/test-runs/<run-id>/log.txt` and `records/timing/<run-id>.jsonl`. `run-id` is the
UTC time `YYYYMMDDTHHMMSSZ` and the short revision. A timing line holds `run_id`, `revision`,
`dirty`, `environment` (`lean`, `python`, `host`, container image digest), `test`, `input`, and
`setup_ms`, `fixture_ms`, `construction_ms`, `nested_ms`, `total_ms`. The commit of a milestone
adds the new records. **Source**: constitution E6, E7; [KS] SC-016.

## R7. Tier 1 and the hooks

**Decision**: `just test-tier1` runs the mathlib-free worker build, the boundary grep, the
no-`sorry` scan of `worker/`, strict mypy, the core-only roundtrip and the tier-1 pytest files
of the plan. `test-commit` runs `test-tier1`. `test-push` and `test-ci` run `test`. **Source**:
constitution E1, E4.

## R8. Toolchain target

**Decision**: Lean `v4.36.0-rc2` and, for NbDsl, Mathlib `master` at 5d0d3c0, the pins of
lean-cas-dsl `main`. **Source**: constitution J9; lean-cas-dsl `AGENTS.md` "Source location"
(`main` pins the toolchain and Mathlib of the research image; issue #90).

## R9. Consumer qualification revision

**Decision**: `scripts/qualify_consumer.sh` pins the lean-cas-dsl revision that contains its
T038 and T085 (one session for the notebook and the worker connection to its transactions).
That revision is the input of T012. The present pin 4c6feda (2026-07-31) and its `sage -python`
start are replaced. **Source**: [KT] T085 and T093; the digest gap G6.
