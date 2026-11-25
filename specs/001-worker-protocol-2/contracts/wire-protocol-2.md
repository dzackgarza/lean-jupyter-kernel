# Contract: wire protocol 2 of this repository

The session contract is [NS] (lean-cas-dsl
`specs/001-categorical-research-language/contracts/notebook-session.md`). This file names the
frames that this repository implements and the points that [NS] leaves to it. It does not
restate [NS]; where they differ, [NS] holds and this file is corrected.

| Frame | Direction | [NS] section | Repository decision |
| --- | --- | --- | --- |
| `ready` | worker → client | §2 | `lean` is the `Lean.versionString` of the build |
| `hello` and its acknowledgement | both | §2 | Before it, only `hello`, `version`, `shutdown` |
| `execute` | client → worker | §3.1 | The client always names `parent_snapshot` (research R4) |
| execute reply | worker → client | §3.1 | A missing parent is `status:"unavailable"` (research R1) |
| `inspect`, `complete`, `is_complete` | client → worker | §3.2 | Unchanged |
| `cancel` | client → worker | §3.3 | The cooperative reply carries `drain` (research R3) |
| `commit_status` | client → worker | §3.3 | Carries `drain` for a cancelled or draining target (research R3) |
| `protocol_error` | worker → client | §3.0 | Unknown operations use it (research R2) |
| `shutdown` | client → worker | §2 | Ends the session; the client reports generation loss |

`drain` value:

```json
{"state": "drained" | "draining" | "cleanup_unacknowledged",
 "failures": [{"request_id": <provider request ID>, "reason": "<text>"}]}
```

`docs/protocol.md` is the reader-facing description of these frames and agrees with this table.
