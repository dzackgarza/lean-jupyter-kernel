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
`draining : BaseIO Bool`. `DrainReport` is `drained`, `draining` or `cleanup_unacknowledged` with
its failures. `commit_status` and a cooperative `cancel` reply carry
`"drain": {"state": …, "failures": [{"request_id": <n>, "reason": "<text>"}]}` for a target that
is cancelled or draining. For the CAS plugin the value comes from the kernel: `draining` when
`CellTransaction.draining` is true; `cleanup_unacknowledged` when it is false and
`FramedConnection.cleanupFailures` of the cell's connections is nonempty, with one failure for
each provider request ID and reason that it holds; `drained` otherwise. The cell states
`draining` and `cleanup_unacknowledged` are distinct from the resource reasons `busy_draining`
and `cancel_unacknowledged` of [NS], which answer a request.
**Source**: [NS] §3.3 (a cancelled cell drains its exact in-flight frames; an engine that does not
reply leaves a draining or busy state; an unacknowledged worker cancellation is
`unavailable/cancel_unacknowledged`); [NS] fixes no field for the report, so its wire form is a
point that [NS] leaves to this repository (`contracts/wire-protocol-2.md`); kernel runtime
contract §7 (a call during the drain is `unavailable/busy_draining`; an unacknowledged drain
persists until explicit force or actual loss; a lost cleanup reply is recorded and not resent);
lean-cas-dsl `tasks.md`, "Unreached code", row T089 (the worker carries the report in the cell
status, T091); the kernel branch at `6808bc0`: `CellTransaction.draining : BaseIO Bool`
(`CasRuntime/Transaction.lean:734`) and `FramedConnection.cleanupFailures : BaseIO (Array (Nat ×
String))` (`CasRuntime/Connection.lean:275`).

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

**Decision**: the qualification revision of lean-cas-dsl is the head, at the time T012 runs, of
the lean-cas-dsl branch that holds the kernel source (lean-cas-dsl `AGENTS.md`, "Source
location": `integration/kernel-v1-20261106` until its pull request #87 merges, then `main`). It
qualifies only when its `specs/001-categorical-research-language/tasks.md` marks K:T038, K:T085
and K:T090 complete, the kernel tasks that T012 consumes, and when its `lean-toolchain` equals the
toolchain of this repository (J9). T012 writes its full hash into `scripts/qualify_consumer.sh`
and into the body of the T012 commit. The script exits nonzero on a revision that lacks one of
the three tasks or has another toolchain. The present pin 4c6feda (2026-07-31) and its
`sage -python` start are replaced.
**Source**: [KT] T038, T085, T090 and T093; constitution J9 (one toolchain for the worker and the
plugin oleans) and E1 (tier 3 uses a real `KernelSession`); lean-cas-dsl `AGENTS.md`, "Source
location"; the digest gap G6.
