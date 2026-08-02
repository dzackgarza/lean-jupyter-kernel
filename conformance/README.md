# Semantic conformance

Installed-kernelspec journeys. NbDsl owns kernel-neutral laws; lean-cas-dsl
owns only extension-shaped boundaries. Qualification owns the frozen consumer
checkout and exports `CONFORMANCE_CAS_DSL`.

```bash
just conformance             # NbDsl
just conformance-external    # casdsl (needs CONFORMANCE_CAS_DSL)

pytest conformance/test_semantic.py -k nbdsl
pytest conformance/test_semantic.py -k casdsl
```

`LEAN_NUM_THREADS=1`. Do not overlap with `scripts/check.sh` or consumer
qualification on memory-constrained hosts.

| id | proves |
| --- | --- |
| NbDsl journeys | success commit, error/parse rollback, output transport, cancel, Lean queries, recovery, independent-session absence |
| casdsl extension | extension state visible only in originating session, rich MIME, survives recovery, Sage assert + Lean constant completion |
