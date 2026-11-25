# Quickstart: checking worker protocol 2

All commands run in the shared math container from the repository root.

| Purpose | Command |
| --- | --- |
| Tier 1 (the commit loop) | `just test-tier1` |
| One tier-1 module | `uv run --project nbdsl_kernel pytest nbdsl_kernel/tests/test_request_controls.py` |
| Tier 2 (push and milestone) | `just test` |
| Tier 3 (CAS consumer) | `scripts/qualify_consumer.sh <lean-cas-dsl revision>` |
| Language-server channel (tier 2, after T017) | `jupyterlab_nbdsl/ui-tests/language-server.spec.ts` through `just test` |

After a run, the log is in `records/test-runs/<run-id>/log.txt` and the timing records are in
`records/timing/<run-id>.jsonl`. A notebook session writes its application logs to the Jupyter
runtime directory as `nbdsl-<kernel id>.worker.jsonl` and `nbdsl-<kernel id>.client.jsonl`.

`just test-tier1` exists after task T002.
