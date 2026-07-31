# Semantic conformance

One kernel-owned law set, run unchanged against every plugin profile.

```bash
just conformance             # in-repository NbDsl reference
just conformance-external    # external plugin; CONFORMANCE_CAS_DSL selects the checkout

python3 conformance/runner.py conformance/nbdsl.toml
python3 conformance/runner.py conformance/lean-cas-dsl.toml \
    [--source-dir DIR] [--kernel-name NAME] [--output result.json]
```

The result JSON goes to stdout unless `--output` names a file; a per-law
summary and the verdict always go to stderr. Exit status is `0` only when every
law passes, `1` on a law failure, and `2` when the profile or the environment it
names is unusable — a missing kernelspec, a kernelspec pointing at a different
checkout, or a profile pinning a commit the checkout is not at.

Everything runs through the ordinary Jupyter protocol against an installed
kernelspec: `execute_request`, `complete_request`, `inspect_request`, a real
`interrupt_request`, and a real `SIGKILL` of the worker process group. No mocks,
no source-shape checks, no way to skip a law.

**Resource contract:** at most one mathlib-loaded worker is alive at a time. The
candidate session is shut down before the independent control session starts —
the laws compare observations, not simultaneity — and each session kills any
worker that outlives its kernel. The runner waits for free memory before
starting one rather than swapping the machine.

## The laws

| id | what it proves |
| --- | --- |
| `registration-isolated` | a second independent session, running the same cells minus the registration, cannot make the candidate's observation |
| `success-commits` | the discriminating command commits exactly its observation change: unobservable before, the canonical projection after, unchanged when observed again |
| `error-rolls-back` | a failing command leaves the pre/post structured observation equal |
| `cancellation-rolls-back` | cooperative cancellation at a real elaboration checkpoint discards the cancelled cell's registration and leaves the committed observation equal |
| `replay-reconstructs` | with the session cache invalidated, worker death recovers by replaying committed sources and reconstructs the same observation |
| `restart-reconstructs` | real worker process death plus the production restart path reconstructs the committed observation |
| `completion-sees-environment` | completion discriminates, and answers about the environment that registered the object |
| `inspection-sees-environment` | inspection discriminates, and answers about that environment |
| `output-control-separated` | frame-shaped output stays ordinary output at the Jupyter boundary, and an independent decoder confirms it never became a control frame |

The identifiers are contract. A profile that cannot satisfy one **fails** it, and
the law's boundary observation records what both environments actually answered
— which is the evidence an API decision needs.

Three laws are deliberately hard to satisfy by accident:

- **Cancellation** is decided on the worker process, not the reply text. The
  interrupt *escalation* path also answers `Interrupted`, but only after killing
  the worker, so the law requires the same worker pids alive before and after.
- **Restart and replay** cannot be satisfied by one code path.
  `restart-reconstructs` accepts whichever recovery route the kernel takes and
  records it; `replay-reconstructs` first invalidates the session cache (an open
  `section` cannot be serialised) and then *requires* the replay route.
- **Output separation** is proven twice: once at the Jupyter boundary, and once
  by decoding the worker's frames with the independent oracle codec in
  `nbdsl_kernel/tests/roundtrip.py`. That codec deliberately duplicates
  production's, so a codec bug cannot pass both sides.

### Completion and inspection under plugin API v1

Both query laws assert three things, in the candidate **and** the control
session: a name that exists nowhere is not found; a prelude constant answers
with **its own signature**, not merely `found: true`; and the profile's
registered name answers according to how the plugin registers it.

`registration.shape` says whether the plugin's registration creates a Lean
constant or lives only in a persistent env extension. Under plugin API v1
`complete`/`inspect` are constant-faithful, so:

- `shape = "constant"` — the strong form: visible in the registering
  environment, invisible in an untouched one.
- `shape = "extension"` — the honest negative: invisible in both. Visibility of
  extension state through these queries is outside the v1 law set and is
  recorded per profile in the result as
  `"extension_state_visibility": "deferred: plugin API v2 demand"`, never
  silently omitted.

The declaration is falsified in both directions, so it cannot be used to dodge:
a `constant` the registering session cannot see fails, and an `extension` the
boundary *can* see fails too.

## What a profile may contain

Profiles are data. They select the plugin package and prelude, supply the cells
to execute, name the cancellation point, declare the registration shape, and
describe the payload the laws read back — the expected MIME types and the
canonical projection of the plugin-authored structured output.

A profile may **not** supply law code, expected success booleans, or result
overrides. `load_profile` rejects any key named `expect`, `status`, `verdict`,
`skip`, `xfail`, `override`, `allow_failure` and their relatives anywhere in the
file, and requires every section the laws consume: `[profile]`, `[plugin]`,
`[registration]`, `[observation]`, `[control]`, `[failure]`, `[cancellation]`,
`[replay]`, `[completion]`, `[inspection]`, `[output]`.

## The result

A single JSON object identifying the kernel commit and its `release.toml`
declaration; the plugin source, the commit the profile pins, the commit observed
in the checkout under test and whether it was dirty, and **how that checkout was
resolved** (`--source-dir`, the profile's `source_env`, or the local fallback —
the fallback is developer convenience and never CI evidence); the kernelspec and
its Lean toolchain; the runtime provenance comm (recorded as `absent` when the
kernel opens none — no law depends on it yet); and for every law its status,
boundary observation, and the fault it detects.
