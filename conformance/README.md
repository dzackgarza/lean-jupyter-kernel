# Semantic conformance

Ten kernel-owned laws, proven through the ordinary Jupyter protocol against an
installed kernelspec. Plugin vocabulary lives as frozen dataclasses in
`test_semantic.py` (NbDsl in-repo, lean-cas-dsl external).

```bash
just conformance             # NbDsl full matrix
just conformance-external    # lean-cas-dsl (needs checkout)

pytest conformance/test_semantic.py -k nbdsl
pytest conformance/test_semantic.py -k 'lean-cas-dsl'
```

Per plugin case: one ordered candidate matrix (success / error / parse /
output-jupyter / cancel / restart / replay), one independent control session
(registration isolation + completion/inspection), and one independent frame
oracle (`roundtrip.py`). lean-cas-dsl is skipped unless `CONFORMANCE_CAS_DSL`
or `../lean-cas-dsl` exists.

Resource contract: `LEAN_NUM_THREADS=1`, `NBDSL_CONFORMANCE_LOCK` flock, wait
for free memory before starting a mathlib worker. At most one such worker is
alive at a time — candidate closes before control. Do not run concurrently with
`scripts/check.sh` or consumer qualification.

| id | proves |
| --- | --- |
| `registration-isolated` | control session cannot make the candidate observation |
| `success-commits` | registration commits exactly its observation change |
| `error-rolls-back` | failing cell discards candidate state and buffered output |
| `parse-error-rolls-back` | malformed tail same rollback |
| `cancellation-rolls-back` | cooperative interrupt (same worker pids) discards candidate |
| `restart-reconstructs` | SIGKILL + restart restores observation/queries; leaks stay absent |
| `replay-reconstructs` | cache-invalidated recovery uses replay route; leaks stay absent |
| `completion-sees-environment` | complete discriminates garbage / prelude / registered |
| `inspection-sees-environment` | inspect discriminates the same triad |
| `output-control-separated` | Jupyter boundary + independent frame decoder |

Journey 1 is `test_clean_install.py`. Journey 6 is `scripts/qualify_consumer.sh`.
