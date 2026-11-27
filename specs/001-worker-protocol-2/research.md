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
lean-cas-dsl `tasks.md`, T089 (it connects `FramedConnection.cleanupFailures` to the drain report
of the cell, and the worker carries the report in the cell status, T091); the kernel branch at `6808bc0`: `CellTransaction.draining : BaseIO Bool`
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
qualifies only when its `lean-toolchain` equals the toolchain of this repository (J9) and its
tasks file marks K:T038 complete. The qualification consumes the notebook-session source of K:T085
and K:T090, which close on their own checks before it, and it is the notebook path of the notebook
checkpoint N1 at K:T093; a revision without their notebook-session code fails the qualification
notebook itself. T012 writes its full hash into `scripts/qualify_consumer.sh` and into
the body of the T012 commit. The script exits nonzero on a revision with another toolchain or with
K:T038 unchecked. The present pin 4c6feda (2026-07-31), its `sage -python` start and the CI step
that provisions Sage 10.7 for that start are replaced: the qualification job runs in the research
image (constitution E5); this is the notebook-launch part of K:T153.
**Source**: [KT] T038, T085, T090, T093 and T153; constitution J9 (one toolchain for the worker
and the plugin oleans), E1 (tier 3 uses a real `KernelSession`) and E5; lean-cas-dsl `AGENTS.md`,
"Source location"; the digest gap G6; `.github/workflows/ci.yml` (Sage 10.7 through micromamba for
the `sage -python` start of the frozen consumer baseline).

## R10. The Lean language server of issue #20

**Decision**: the language server serves the Lean cells of the `nbdsl` kernelspec and of the
native session through a JupyterLab channel that hosts the upstream infoview (FR-018). It is not a
task of the notebook unit, and it is off on `casdsl` (FR-019). Its tasks T016 (the spike of the
two adapters, plan "The Lean language server") and T017 follow T014, so that the release that
lean-cas-dsl T093 locks does not wait for them; their input is T011, whose worker log observes that
the channel sends nothing to the worker.
**Source**: issue #20 and its comment of 2026-10-25 (the infoview host API `EditorApi` and
`InfoviewApi`, the RPC session that the host keeps alive, the separating two-cell specimen; the
`jupyterlab-lsp` virtual document and its `language_info.file_extension` and MIME requirements);
[KS] User Stories 7 and 8, FR-034 to FR-038 and FR-140 (no notebook requirement asks for a
language server; FR-035 and User Story 7, scenario 2, reject an inspection endpoint that executes
text); [KT], the notebook unit (T083 to T093, T010, T097 to T099, T346 to T348, T325), which holds
no language-server task; [NS] §3.2 (inspection passes no candidate text to elaboration);
constitution J1, J4 and J5.
**Reason**: a language server elaborates uncommitted text on every edit. For a Lean cell of NbDsl
or of the native session that is the editor behaviour of Lean. For a CAS cell, elaboration
dispatches computations, so a CAS notebook can send no cell text to a language server.
**Rejected**: answering Jupyter `inspect` and `complete` from the language server, which
elaborates candidate text (J5, FR-005); a REPL-only kernel, which issue #20 excludes.

## R11. Lean commands in cells

**Decision**: a cell is elaborated by `Worker/Frontend.lean` through the plugin; an ordinary Lean
command elaborates in the environment of the parent snapshot and its declarations enter the
committed snapshot like any other cell result. T015 checks it through the native plugin, the
language of tier 1, and the CAS plugin receives the same worker path (K:T347).
**Source**: [KS] FR-140; [KT] T347 (its files include `worker/Worker.lean` of this repository).
