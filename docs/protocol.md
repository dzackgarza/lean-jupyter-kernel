# Worker wire protocol 2

The independent raw-wire tests are `nbdsl_kernel/tests/test_native_v2.py`
and `nbdsl_kernel/tests/roundtrip.py`. The typed adapter lives in
`nbdsl_kernel/nbdsl_kernel/protocol.py`.

## Transport and negotiation

Two inherited pipes carry requests and replies, separate from user stdout and
stderr. A frame is its ASCII byte length, a newline, and that many bytes of
UTF-8 JSON. Each worker has a fresh nonce and one frozen realization profile.
Its unsolicited `ready` frame contains protocol 2, worker_nonce, snapshot
`"0"`, realization_profile (id and sha256), Lean version, PID, release, and
these required features:

- cas-session/2, explicit-parent/2, atomic-cell/2
- inspect-environment/2, complete-environment/2, cancel-by-request/2
- no-replay/2, no-session-cache/2

Before sending any candidate source, the client verifies the version,
features and configured profile digest, then exchanges

```json
{"op":"hello","protocol":2,"worker_nonce":"actual nonce","session_policy":"cas_no_replay"}
```

with an identical acknowledgement plus `"status":"ok"`. Incompatible or
unacknowledged sessions do not receive source. EOF cancels queued and active
work and closes the session; it does not replay the queue into another worker.

All post-handshake operations carry protocol 2, the actual worker_nonce, a
fresh string request_id and op. Snapshot serials are canonical decimal
strings, scoped to the nonce. The worker consumes each request ID once,
before operation-specific validation. A duplicate yields
`{op:"protocol_error",worker_nonce,offending_request_id,reason:"duplicate_request_id"}`;
it is not a result of the original request. Unknown operations or malformed
fields are protocol errors. A foreign nonce does not claim an ID.

## Execution and settlement

`execute` takes code, cell_id, parent_snapshot and
session_policy="cas_no_replay". It executes one explicitly submitted cell
against that committed parent. No automatic execution of predecessors,
cache restoration, restart/replay, retry or migration is authorized.

An ok reply names parent_snapshot, a new snapshot, diagnostics, sorries,
outputs and commit. The latter contains transaction_id, output_batch_id,
profile_sha256 and result_refs. Each output contains result_id, mime,
metadata and optional display_id. MIME bundles must have usable text/plain;
text/latex and other representations may be included in the same event.
Output delivery is deduplicated by worker nonce, batch and result identity.

Error and cancelled replies retain the parent snapshot and publish no
commit or outputs. Failure strata and resource reasons are not interchangeable.
An unavailable execution after communication loss may be indeterminate;
this is neither a guarantee of rollback nor permission to resend.

`cancel` takes target_request_id and mode ("cooperative" or "force") and
has its own fresh request ID. The reader handles it out of band. Cancellation
and commit share one linearization gate. Reply status is cancelled, forced
(with invalidated_owners), already_committed (with actual snapshot and
receipt), or not_found. An unacknowledged cooperative cancellation does not
authorize force or retry. The original execute request has its own settlement.

`commit_status` takes snapshot and target_request_id. It reads a visible
committed ancestor's receipt, reports active pending work or unavailable.
It does not retrieve a cached execution result, start a worker or dispatch.

## Inert queries

All queries name a committed snapshot and carry candidate code solely for
lexical selection. They never elaborate it or invoke a user extension,
provider, lazy field, pretty-printer or documentation callback.

- `inspect`: mode="environment", code, cursor, detail_level. Returns found,
  name, type, doc and optional immutable details. Unexecuted locals need
  not be present. A DSL can prepare exact selected mathematical descriptors
  at its authorized cell boundary.
- `complete`: mode="environment", code, cursor. Returns matches,
  cursor_start, cursor_end. Reads committed names and prepared members,
  including lexical shadowing.
- `is_complete`: mode="syntax", code. Returns complete, incomplete,
  invalid or unknown using fixed lexical classification. Unknown grammar
  is not passed to an executable environment parser.

Cursor positions and columns are Unicode code points; lines are 1-based,
columns 0-based. An absent or incompatible worker yields an unavailable
reply, rather than being bootstrapped by a query.

## Other operations

`describe` returns protocol, current committed snapshot and frozen profile.
`shutdown` cancels pending work and closes the owned session. Neither
`save_session` nor `load_session` is a protocol-2 operation.

Protocol 2 does not offer durable exactly-once external effects. Retained
snapshots do not resurrect provider connections or restore consumed rights.
The CAS provider protocol is independently negotiated.
