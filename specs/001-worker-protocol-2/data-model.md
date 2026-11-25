# Data model: Worker protocol 2

| Entity | Owner | Fields | Rules |
| --- | --- | --- | --- |
| Worker session | worker (`Worker.lean`, `Session`) | nonce, realization profile (`id`, `sha256`), snapshots, current serial, plugin | One per process. The nonce is fresh at each start |
| Controls | worker (`Worker.lean`, `Controls`) | claimed `(nonce, request_id)` set, pending executions, draining handles | Non-rollbackable. An ID is never removed |
| Snapshot | worker | serial (decimal string), parent serial, command state, cell ID | Immutable. Scoped to the nonce |
| Cell transaction | plugin through `Worker.Cell.Active` | parent, staged completions, `cancel`, `force`, `drainReport` | One active per worker; others queue |
| Drain report | plugin | `state` in `drained`, `draining`, `cleanup_unacknowledged`; `failures`, each a provider `request_id` and a `reason` | Carried in `commit_status` and the cooperative `cancel` reply (research R3) |
| Committed receipt | worker (`Cell.CommittedReceipt`) | `transaction_id`, `output_batch_id`, `profile_sha256`, `result_refs`, snapshot | Visible only in snapshots that contain it |
| Output batch | worker, published by the client | `result_id`, `mime` (`text/plain`, `text/latex` where supplied), `metadata`, `display_id` | Published once, after commit |
| Client session | client (`worker/client.py`) | process, nonce, validated `ready`, the last committed snapshot | Never restarts by itself |
| Language-server document | JupyterLab channel (`jupyterlab_nbdsl`) | the Lean cells in cell order, the map from each cell to its line range, the server session | Separate from the worker session; never on `casdsl` (FR-019) |

State of an execution: `queued` → `active` → one of `committed`, `error`, `cancelled`,
`unavailable`. A `cancelled` execution has a drain report in `drained`, `draining` or
`cleanup_unacknowledged`.
