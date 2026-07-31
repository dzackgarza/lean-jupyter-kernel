# Reliable, compatible Lean notebooks: programme delivery plan

> Tier: workstream / organizational
> Parent plan: root / researcher-facing programme
> Externalized fit: the single programme-sized `lean-jupyter-kernel` draft PR; it closes
> #2, #3, #4, and #6 and references the direct-to-main and post-merge work in #5, #7,
> and #8
> Delivery constraint: every `lean-jupyter-kernel` code, packaging, CI, repository
> configuration, compatibility, and release-control change in this programme ships in
> this one PR

## Contents

- Researcher-visible after-state
- PR claim and externalization fit
- Before and after contract
- Scope, constraints, and preserved behavior
- Fixed design decisions
- Execution graph
- Workstreams 1–7
- System-level proof matrix
- Non-goals and stop conditions
- Completion condition and public traceability

## Researcher-visible after-state

A researcher installs exact release `v1.1.0`, selects a Lean project and plugin, and
starts the installed kernel in ordinary Jupyter or JupyterLab. The kernel starts the
worker built from the declared immutable kernel source under the declared Lean
toolchain. This remains true when the worker is a direct local path dependency or is
nested under a Git/Lake plugin dependency.

The resulting notebook has one mathematical environment contract. Successful Lean and
DSL commands commit their environment changes. Failed and cooperatively cancelled
commands commit nothing. Forced source replay and recovery after real worker death
reconstruct the same committed state. Completion and inspection see objects registered
in the active environment and do not see them in an independent environment. Plugin
output cannot be parsed as worker control traffic.

NbDsl and the external `lean-cas-dsl` plugin satisfy these same kernel-owned laws. The
external profile supplies only plugin-specific commands and structured observations; it
does not redefine success. The real `lean-cas-dsl` Sage/Jupyter boundary passes first
against the exact kernel candidate and then against the published release.

The installed JupyterLab package is the governed, built extension artifact. It activates
in a clean JupyterLab 4 environment. If this PR changes visible frontend behavior, the
changed behavior is rendered and inspected in real JupyterLab.

One authored `release.toml` owns the static compatibility contract. Generated package
declarations consume it; build provenance adds the exact non-self-referential commit and
artifact hashes. Runtime observations, downstream provenance, CI qualification, package
registries, and tag readback agree with that derived identity. Live `main` protection
admits changes through PRs and required CI and forbids force pushes and branch deletion.

The programme ends only after `lean-cas-dsl` adopts the published immutable identity
through both dependency channels and repeats its clean build, semantic conformance,
runtime-provenance, and Sage-backed notebook proof. Merging the kernel PR or publishing
the tag alone is not completion.

## PR claim and externalization fit

This PR claims the complete kernel-repository transformation:

- generic worker/session semantics with structured, discriminating observations;
- clean adapter and kernelspec installation for both supported dependency shapes;
- kernel-owned semantic conformance for NbDsl and one immutable external plugin;
- a distributable and activating JupyterLab extension;
- one governed compatibility and release identity;
- exact-candidate downstream qualification;
- compact claim-specific CI and exact-release-head qualification; and
- repository-owned release controls and live ruleset verification.

The PR also owns the kernel side of the external-consumer handoff: immutable consumer
selection, exact-candidate overrides for both dependency channels, conformance and
Sage-backed qualification, provenance publication, and unchanged-worktree proof.

The PR cannot contain the post-release edit to the separate `lean-cas-dsl` repository.
That edit remains part of this programme's completion condition and must use the
published identity proved by this PR. It is not deferred optional work.

Plan fit:

- Tree root: this researcher-facing compatibility and release programme.
- PR claim set: all `lean-jupyter-kernel` work described here, in one PR.
- Public traceability: #2–#8.
- Milestone and release identity: `1.1.0` / `v1.1.0`.
- Issues to close on merge: only requirements fully satisfied by the kernel PR at merge.
- Issues to reference: any issue whose release publication or downstream repin
  obligation remains open.
- Proof claimed by the PR: current-tree kernel behavior, clean packaging and
  installation, exact-candidate consumer qualification, compatibility consistency, and
  readiness of exact-head release controls.
- Proof completed after merge: qualification of the actual release commit, tag-to-commit
  readback, publication to GitHub, PyPI, and npm, and consumer adoption of the
  published identity.

Do not split kernel work into stacked or subsystem PRs. Commits may provide reviewable
checkpoints inside this PR, but no checkpoint narrows the PR's final claim.

## Before and after contract

| Boundary | Before | Required after |
| --- | --- | --- |
| Plugin semantics | Substantial NbDsl-specific behavior and proof | One kernel-owned law set applied to NbDsl and immutable `lean-cas-dsl` profiles |
| State transactions | Worker snapshots already commit only successful cells | Structured observations prove exact success commit, error/cancellation rollback, replay, restart, isolation, completion, and inspection for both plugins |
| Transport | Dedicated framed control descriptors and typed replies | Existing isolation remains, and both sides advertise and validate the governed wire identity |
| Adapter installation | Kernelspec install and several worker lookup layouts work from developer-oriented builds | Built adapter installation starts the intended worker from clean local-path and nested-Git/Lake projects and reads back its provenance |
| Frontend distribution | Node build and tests exist; Python and npm versions disagree; a release wheel is unproved | One versioned wheel contains the built extension and activates in clean JupyterLab 4 |
| Compatibility | Versions and toolchains are independently authored across package files | `release.toml` is the only authored static contract; generated projections, build provenance, artifacts, and runtime readback derive from it and reject mismatch |
| External consumer | Required synchronization and runtime proof are reported but unverified here | Both dependency channels name one immutable kernel; exact candidate and published release pass the real Sage/Jupyter boundary |
| Release | The broad `v1` release points at 1.0.0 source and publishes no installable artifacts | `v1.1.0` publishes the governed Lean source, Python distributions, npm package, checksums, and provenance from one qualified commit, then the consumer adopts it |
| Governance | Required live branch rules are not proved | Native GitHub protection is configured and read back from the live repository |

## Scope, constraints, and preserved behavior

### Included

- `worker/` semantic transaction, observation, protocol identity, replay, and restart
  behavior needed for generic conformance.
- `nbdsl_kernel/` process, transport, worker resolution, runtime provenance, clean
  installation, kernelspec, interrupt, replay, and document recovery behavior.
- `dsls/nbdsl/` as the in-repository reference conformance profile.
- `jupyterlab_nbdsl/` build, wheel contents, version alignment, clean installation,
  activation, and changed-behavior browser proof.
- The authoritative `release.toml`, generated package projections, build-time provenance,
  negative mismatch proof, CI composition, release-head qualification, registry
  publication, and live ruleset readback.
- Exact-candidate qualification against an immutable `lean-cas-dsl` commit without
  committing or pushing consumer overrides.
- The explicit post-release handoff and consumer repin proof required to finish the
  programme.

### Preserved invariants

- Lean owns parsing, elaboration, proof checking, semantic state, completion,
  inspection, and completeness classification.
- `worker/` remains mathlib-free and does not import NbDsl or an external consumer.
  Plugin packages depend on the `Worker` library, never the reverse.
- Each execute request elaborates from its selected parent snapshot. Only success
  commits the candidate state; errors and cooperative cancellation return the parent.
- Request-local MIME output remains rendering state. Persistent DSL semantics remain in
  Lean environment extensions.
- Control messages remain byte-length-prefixed UTF-8 JSON on dedicated inherited file
  descriptors, correlated by request ID, independently decodable, and absent from
  stdout.
- Malformed or incompatible replies fail visibly. Missing projects, workers,
  toolchains, or required build state also fail visibly.
- Process-group termination, interrupt escalation, cache recovery, source replay, loud
  init failure, and document-prefix recovery remain production paths.
- The existing bare-worker and installed-kernelspec obligations remain mandatory,
  including diagnostics, sorry goals, Unicode positions, atomicity, scopes/options,
  registry state, completeness, output, EOF, interrupts, stale-cell behavior, and typed
  upstream failures.
- Existing Lean highlighting, document synchronization, stale-cell presentation, and
  path MIME rendering remain compatible unless this PR deliberately changes and proves
  them.
- The opt-in bubblewrap feature and its current scope remain intact.
- No test, CI job, record, issue state, or release metadata substitutes for the runtime
  behavior it witnesses.

### Prohibitions

- No fallback worker, copied worker, system worker, guessed path, synthesized empty
  result, compatibility shim, or silent protocol downgrade.
- No hard-coded downstream consumer name or NbDsl registry shape in the generic worker
  contract.
- No editable checkout, reused source `.venv`, development labextension symlink, or
  preinstalled kernelspec as clean-install evidence.
- No mutation of consumer semantics during candidate qualification.
- No floating Git reference or broad `v1` tag as an immutable identity.
- No source-shape, log-string, helper-only, mock, or status-only proof where a real
  runtime boundary is required.
- No release tag after the qualified tree changes.

## Fixed design decisions

These choices define the implementation. They are not gates that may be resolved to a
smaller mechanism later.

1. **Release identity: `1.1.0` / `v1.1.0`.** The existing `v1` tag points at
   `0008bda2c69f76abceab92a0b4a4e1b32d65f5c9`, whose package declarations are
   `1.0.0`, and its GitHub release has no assets. Preserve that historical tag. The
   semantic-conformance, provenance, and distributable-frontend additions form the
   backward-compatible 1.1 feature release.
2. **One authored compatibility source.** Add root `release.toml` with schema version,
   release SemVer, Lean toolchain, Mathlib revision, plugin API version `1`, and wire
   protocol version `1`. Derive tag `v1.1.0` from the SemVer. A repository-owned
   generator rewrites the Lake, Python, npm, and toolchain declarations from this file;
   those files are generated projections, not independent authorities. Its check mode
   fails on any diff.
3. **Non-self-referential build provenance.** Do not put the repository's own commit in
   tracked `release.toml`. The Lake and Hatch build paths generate Lean and Python build
   information from `release.toml` plus the exact clean Git commit. Missing Git identity,
   a dirty release tree, or an unknown value is a hard failure. The worker embeds that
   identity in `ready` and `describe`; the adapter embeds its own, hashes the executed
   worker, rejects disagreement before accepting cells, and exposes the combined object
   through an `nbdsl_provenance` Jupyter comm. A release-provenance artifact binds the
   commit, manifest hash, package files, worker binary, wheels, sdist, and npm tarball by
   SHA-256.
4. **Semantic observations use plugin API v1.** Do not add a registry-shaped Worker API.
   Kernel-owned TOML profiles drive ordinary `execute`, `complete`, and `inspect`
   requests and read plugin-authored structured MIME. NbDsl uses its registry diagnostic
   commands; `lean-cas-dsl` uses its existing capabilities, route, gap, and canonical-map
   MIME bundles. Profiles supply inputs and observations but cannot alter the shared
   laws or result schema.
5. **Official JupyterLab wheel builder.** Adopt the current JupyterLab extension-template
   pattern: Hatchling, `hatch-nodejs-version`, `jupyter-builder>=1,<2`, and the
   `hatch-jupyter-builder` npm build hook running `jlpm build:prod`. The wheel maps the
   generated labextension to `share/jupyter/labextensions/jupyterlab_nbdsl` and requires
   its `package.json` and production static entrypoints. Python frontend version metadata
   reads the generated npm version instead of declaring another version.
6. **Consumer baseline and transaction route.** *Plan update, 2026-07-31 (landed with
   repeated baseline proof, per this decision's own substitution rule):* the baseline
   transaction started from consumer `main` at
   `47bce1626a2f5e340557eaa131e5153d64fd6b06` — the head after the owner-directed #31
   SPEC-conformance queue closed, superseding the pre-#31 commit `c756308…` named when
   this plan was authored — and pinned BOTH dependency channels to kernel commit
   `92c0caefb9587f4fee0a0e67e79afd91c8cb4f49` rather than `0008bda…`: the adapter at
   `0008bda…` predates the subDir worker-exe resolution fix (`92c0cae`, Python-only,
   worker Lean source identical) that the consumer's `/ "worker"` git dependency shape
   requires. The transaction landed directly on consumer `main` as
   `1b6822aa80988d5ef06aafd4f430b22e7d41b7bb` and its clean-checkout proof passed
   (full build, no-sorry, real Sage roundtrip, 127 kernel E2E; evidence on #5). That
   commit is the FROZEN QUALIFICATION BASELINE, recorded in
   `conformance/lean-cas-dsl.toml`. *(Second dated update, later on 2026-07-31: the
   baseline was promoted to `4c6fedafccfe77af80ac632efa780e967d726c14` after the
   owner-directed cas#32/cas#33 fixes — named refusals for held features, acceptance
   notebook regenerated — landed on consumer `main` through its full commit and push
   gates; the post-release repin ships from that lineage, and the candidate
   qualification run re-proves the promoted baseline from a clean checkout.)*
   Candidate overrides remain ephemeral. After publication, land the two
   exact-release pins directly on consumer `main` and repeat the proof.
7. **Published artifacts.** Publish `nbdsl-kernel==1.1.0` and
   `jupyterlab-nbdsl==1.1.0` to PyPI, `jupyterlab_nbdsl@1.1.0` to npm, and `v1.1.0`
   as the Lean/Lake and GitHub source identity. Attach both Python wheels and sdists, the
   npm tarball, checksums, and release provenance to the GitHub release. Registry names
   returned not-found responses on 2026-07-30; claim them and configure trusted
   publication before tagging.
8. **Repository protection.** Configure `main` to require PRs and the exact checks
   `worker (mathlib-free gate)`, `NbDsl + kernel round-trip + e2e`,
   `jupyterlab extension`, and `compatibility + external consumer`; forbid force pushes
   and deletion. Require no human approvals while no second reviewer exists.

## Execution graph

### Intrinsic dependency chain

1. Land the direct-to-main consumer baseline transaction (DONE: consumer
   `1b6822aa80988d5ef06aafd4f430b22e7d41b7bb`, both channels at kernel commit
   `92c0caefb9587f4fee0a0e67e79afd91c8cb4f49` per the dated plan update in fixed
   decision 6, clean-checkout proof green, #5 closed).
2. Add `release.toml`, generated package projections, exact build provenance, and the
   runtime identity comparison.
3. Implement the two fixed TOML semantic profiles and apply the shared laws first to
   NbDsl, then to the frozen external consumer.
4. Prove compatible toolchain selection, both worker-resolution layouts, and clean
   adapter/kernelspec installation.
5. Build version `1.1.0` through the official JupyterLab wheel path and prove clean
   JupyterLab activation.
6. Qualify the exact kernel candidate against the frozen consumer without changing its
   worktree.
7. Run the four named required checks on the exact PR head, including generated-
   projection equality, all runtime readbacks, and the deliberate mismatch case.
8. Configure and read back live `main` protection with those four check names.
9. Merge the one kernel PR. Qualify the actual release commit again if its commit differs
   from the qualified PR head.
10. Create `v1.1.0` only after exact-head qualification. Build and publish the selected
    artifacts from that tag, then read back registry versions, artifact hashes, and
    tag-to-commit equality.
11. Land the two exact-release consumer pins directly on consumer `main` and repeat the
    clean build, semantic conformance, Sage/Jupyter E2E, and provenance proof.

Steps 7–11 are strict. PR checks against an earlier commit do not authorize tagging a
different commit, and publication does not authorize declaring completion before the
consumer repin passes.

### Safe parallel work inside the one PR

All work starts from the fixed choices above:

- Semantic-profile and shared-law implementation can proceed beside adapter provenance
  and clean-install fixtures.
- Frontend distributable-wheel work can proceed beside worker/adapter work because both
  consume `release.toml` version `1.1.0`.
- Live ruleset configuration/readback can proceed as soon as all four named checks
  appear on the draft PR.
- Consumer baseline synchronization can proceed beside kernel work, but external
  qualification waits for the resulting immutable consumer commit.
- CI composition can begin with existing proof families, but required status and
  release claims wait for the real new boundary jobs.

Every parallel branch integrates back into the same PR. Generated release projections,
runtime identity, and claim-specific CI output are the integration contracts.

## Workstream 1: Lean worker semantic transaction and recovery

**Owner surfaces:** `worker/Worker.lean`, `worker/Worker/Frontend.lean`,
`worker/Worker/Protocol.lean`, `worker/Worker/SessionCache.lean`,
`worker/Worker/Query.lean`, and `worker/Worker/Output.lean`.

**Before:** snapshot atomicity, replay/cache behavior, completion, inspection, and output
isolation exist, but proof is coupled to NbDsl examples and no governed compatibility
identity joins the worker to the adapter and release.

**After:** the worker preserves its plugin-neutral transaction surface and exposes exact
build identity. The conformance runner proves both profiles through ordinary worker
operations and plugin-authored MIME without importing either plugin into the worker.

Implementation obligations:

- Preserve the selected-parent transaction in `handleExecute`: success commits the
  exact candidate; error and cooperative cancellation return the unchanged parent.
- Keep semantic observation on plugin API v1: profiles execute plugin-authored registry
  diagnostics and compare their canonical MIME payloads before and after success,
  failure, cancellation, replay, restart, completion, inspection, and isolation. Add no
  registry schema or observer callback to the worker.
- Add a real mid-command cancellation checkpoint case and a real process-death case.
  Drive recovery through the production client path in the appropriate REPL/document
  mode.
- Compile the generated Lean build-information module into `nbdsl_worker`; return its
  release, commit, plugin API, wire, and toolchain fields from both `ready` and
  `describe`.
- Keep output request-local and verify that frame-shaped plugin/user output cannot enter
  the control decoder.
- Retain request IDs, diagnostics, info trees, sorry accumulation, Unicode positions,
  prelude import restrictions, unsupported-operation behavior, and clean EOF shutdown.

Acceptance:

- Structured pre/post observations are equal for error and cooperative cancellation and
  differ exactly as expected for success.
- Forced replay and real worker restart reconstruct the committed observation.
- An independent environment lacks the registered object.
- Completion and inspection find the object only in the environment that registered it.
- An independent frame codec decodes control traffic while adversarial plugin/user
  output remains ordinary output.

Stop if either plugin cannot produce the fixed structured observation contract through
plugin API v1, if recovery requires a non-production path, or if a profile-specific
registry leaks into the worker.

## Workstream 2: Python adapter, transport, kernelspec, and installation

**Owner surfaces:** `nbdsl_kernel/nbdsl_kernel/kernel.py`,
`nbdsl_kernel/nbdsl_kernel/worker.py`, `nbdsl_kernel/nbdsl_kernel/protocol.py`,
`nbdsl_kernel/nbdsl_kernel/install.py`, and built Python distribution metadata.

**Before:** the adapter owns the correct process and recovery paths and recognizes
several local layouts, but repository evidence does not prove clean artifact
installation, nested Git/Lake resolution, or runtime identity.

**After:** a clean environment installs the built adapter, installs a kernelspec from a
minimal Lean project, starts the intended worker for each supported dependency shape,
executes a semantic interaction, and reads back matching immutable provenance.

Implementation obligations:

- Preserve `_ensure_worker`, `_ensure_prefix`, `do_execute`, `WorkerClient` request
  correlation, process-session ownership, process-group termination, cache keys, replay,
  cancellation escalation, loud init failure, and document-prefix reconstruction.
- Extend worker discovery only from real Lake/project metadata and supported build-tree
  ownership. A missing or ambiguous intended worker must fail.
- Build minimal clean projects for a local path dependency and for a plugin obtained as
  a nested Git/Lake dependency. Build and execute the resolved worker in both cases.
- Install the adapter artifact and kernelspec in an empty Python/Jupyter environment.
  Run the installed kernelspec through a Jupyter client and perform a meaningful plugin
  state transition.
- Generate adapter build information from the exact same `release.toml` and Git commit.
  On worker start, compare both embedded identities, hash the executed binary, and fail
  before accepting cells on any disagreement.
- Expose the compared identity through the `nbdsl_provenance` Jupyter comm so a clean
  installed-kernelspec test and the external consumer can read it without parsing DSL
  source or inferring a path.
- Keep Pydantic validation at the protocol boundary. Do not turn malformed or
  incompatible frames into success-shaped replies.

Acceptance:

- Each clean project starts the binary owned by its declared dependency graph, not one
  found in the source checkout or system.
- Runtime worker identity, adapter identity, selected prelude, and toolchain agree with
  `release.toml` and generated build provenance.
- Installed-kernelspec observations preserve all existing execution, interrupt,
  completion, inspection, MIME, init, cache/replay, and document-mode obligations.

Stop on undeclared checkout state, an unresolved or ambiguous worker, toolchain
disagreement, or provenance that can only be inferred from a path.

## Workstream 3: plugin contract and shared semantic conformance

**Owner surfaces:** the kernel-owned conformance runner and result model,
`conformance/nbdsl.toml`, `conformance/lean-cas-dsl.toml`, `dsls/nbdsl/` as the
reference plugin, and the frozen `lean-cas-dsl` checkout as the external plugin.

**Before:** NbDsl proves rich behavior, but its examples do not establish a generic
plugin contract.

**After:** one kernel-owned law set runs unchanged against both profiles. A profile
selects a package/prelude and supplies discriminating commands and structured
observations; it cannot weaken the laws or redefine the result model.

Shared laws:

- registration changes only the selected candidate environment;
- success commits exactly that change;
- error and cooperative cancellation leave exact parent state;
- forced replay reconstructs the same state;
- real process death reconstructs state through production restart;
- a second environment remains uncontaminated;
- completion and inspection agree with the current environment; and
- structured output remains separate from independently decoded control frames.

Implementation obligations:

- Extract the laws from the preserved runtime behavior without deleting the broader
  NbDsl cases.
- Keep profile data in the two named TOML files: immutable plugin source,
  package/prelude selection, execute/complete/inspect inputs, cancellation point,
  expected MIME types, canonical projections of the payloads, and semantic
  relationships. Profiles cannot supply law code, expected success booleans, or result
  overrides.
- Run NbDsl from repository source and `lean-cas-dsl` from a clean immutable checkout
  under the same compatible toolchain.
- Publish a result that identifies kernel commit, plugin commit/profile, toolchain,
  runtime provenance, and each law's boundary observation.
- Keep the runner in this repository. Do not create a public SDK or separate conformance
  repository before a second independent external DSL creates that ownership need.

Acceptance requires both profiles to satisfy the same law identifiers and structured
relations. A smaller shared suite does not authorize loss of existing NbDsl behavior.

Stop if candidate qualification needs a semantic consumer patch, if a profile can pass
without exercising the real plugin, or if genericity is claimed from NbDsl-only
examples.

## Workstream 4: JupyterLab extension and distributable packaging

**Owner surfaces:** `jupyterlab_nbdsl/package.json`,
`jupyterlab_nbdsl/pyproject.toml`, the wheel/build configuration, and the three plugins
registered by `jupyterlab_nbdsl/src/index.ts`.

**Before:** frontend unit tests and builds cover pure behavior, but Python and npm
versions disagree and no clean artifact activation proves release packaging.

**After:** generated npm metadata and Python metadata both report `1.1.0`; the PyPI wheel
contains the production labextension, installs in clean JupyterLab 4, and activates
without a development link. The same frontend package is published to npm.

Implementation obligations:

- Generate npm version `1.1.0` from `release.toml`; make the Python distribution read
  that value through `hatch-nodejs-version` instead of declaring its own.
- Replace the manual-build-only Hatch configuration with the official JupyterLab
  extension-template path: Hatchling plus `jupyter-builder>=1,<2` and the
  `hatch-jupyter-builder` npm hook running `jlpm build:prod`; follow the current
  [`jupyterlab/extension-template` `pyproject.toml`](https://github.com/jupyterlab/extension-template/blob/main/template/pyproject.toml.jinja)
  rather than inventing a package-local build convention.
- Require the production `labextension/package.json` and static entrypoints as ensured
  build targets, and map the generated directory and `install.json` into
  `share/jupyter/labextensions/jupyterlab_nbdsl`.
- Clean generated frontend output before every distribution build so the wheel cannot
  consume a developer symlink or stale bundle.
- Inspect wheel contents, install the exact wheel into a clean JupyterLab 4 environment,
  and verify extension discovery and activation. Pack and inspect the npm tarball from
  the same generated metadata.
- Preserve language registration, document comm synchronization, stale-cell classes,
  and NbDsl path MIME validation/rendering.
- Retain node tests for pure functions. If this PR changes browser-visible behavior,
  launch real JupyterLab with the built artifact, render the affected notebook state,
  inspect it, and retain revision-tied evidence.

Acceptance distinguishes build, artifact contents, clean activation, and visual
adequacy. A successful TypeScript build proves none of the latter three by itself.

Stop if the wheel requires `labextension develop`, a source symlink, pre-existing build
output, or an undeclared service environment.

## Workstream 5: compatibility authority, provenance, protection, and publication

**Owner surfaces:** root `release.toml`; a repository-owned release-projection tool;
generated Lake, Python, npm, and toolchain declarations; Lake and Hatch build-information
hooks; runtime provenance; release workflows; and the live GitHub repository ruleset.

**Before:** owned packages mostly declare `1.0.0`, frontend Python declares `0.1.0`,
wire version `1` is embedded in the worker, the broad `v1` GitHub release has no assets,
and live `main` protection is absent.

**After:** `release.toml` is the only authored static compatibility source. It fixes:

- schema version `1`;
- release SemVer `1.1.0`;
- Lean toolchain `leanprover/lean4:v4.32.0`;
- Mathlib revision `v4.32.0`;
- plugin API version `1`; and
- wire protocol version `1`.

The tag is deterministically `v1.1.0`. Build provenance adds the exact clean commit and
artifact hashes because a tracked source file cannot truthfully contain its own commit.

Implementation obligations:

- Add a standard TOML parser-backed projection tool. Its write mode regenerates every
  tool-owned version/toolchain declaration from `release.toml`; its check mode generates
  to a temporary tree and fails on any diff. Mark projections as generated where their
  formats permit comments.
- Generate a Lean build-information module and Python package build-information resource
  from `release.toml` plus the exact clean Git commit. Build and release paths fail on
  missing Git metadata, dirty state, malformed fields, or unknown identity.
- Return the embedded worker identity from `ready` and `describe`. Compare it with the
  adapter build identity before accepting cells, hash the executed worker binary, and
  expose the combined object through `nbdsl_provenance`.
- Generate `release-provenance.json` after building. It contains the release manifest
  hash, commit, tag, package versions, worker hash, distribution filenames, and SHA-256
  hashes. CI checks every built artifact and runtime observation against it.
- Prove the projection checker and runtime comparison each reject a deliberately changed
  governed value. The test must mutate a temporary projection or artifact, never the
  authoritative file.
- Configure live `main` protection for PR admission, the four fixed required checks, no
  force pushes, and no deletion. Read back the active rules from GitHub.
- Qualify the exact release commit after merge. Create `v1.1.0` only after that succeeds;
  build all artifacts from the tag, publish them to GitHub, PyPI, and npm through trusted
  publishers, then read back registry versions, hashes, and tag-to-commit equality.
- Preserve historical `v1`; do not move, delete, or treat it as the immutable governed
  identity.

Acceptance requires a one-way derivation from `release.toml` to generated declarations,
build provenance, built artifacts, runtime observations, registry records, CI revision,
and tag target. A parallel hand-edited record plus a validator does not satisfy this
workstream.

Stop if live rules cannot be read back, trusted publication cannot be configured for
PyPI or npm, the release head changes, a projection or runtime identity disagrees,
or the tag does not resolve to the qualified commit.

## Workstream 6: external `lean-cas-dsl` integration

**Owner boundary:** kernel qualification orchestration in this PR; dependency updates
and the real Sage-backed notebook boundary in the separate consumer repository.

**Before:** consumer commit `c756308851b6b201505a8b6da2ee67b3936c7d73` pinned the
Lake worker channel to kernel commit
`0008bda2c69f76abceab92a0b4a4e1b32d65f5c9`, but its `just setup` adapter URL
floated on kernel `main`.

**After:** one immutable consumer baseline resolves its Lake worker dependency and
Python adapter dependency to the same kernel identity. Qualification can replace both
with the exact candidate SHA ephemerally, prove the candidate, and leave the consumer
unchanged. After publication, the consumer commits both channels to the release identity
and repeats the proof.

Implementation obligations:

- DONE (dated plan update, fixed decision 6): from consumer `main`
  `47bce1626a2f5e340557eaa131e5153d64fd6b06`, both the Lake worker pin and the
  adapter Git URL moved to kernel `92c0caefb9587f4fee0a0e67e79afd91c8cb4f49`;
  the transaction landed directly on consumer `main` as
  `1b6822aa80988d5ef06aafd4f430b22e7d41b7bb`, its clean build and Sage/Jupyter
  proof passed, and that commit is the frozen external profile and qualification
  baseline.
- Store that resulting immutable consumer commit in the kernel's generated qualification
  inputs. Do not substitute a later consumer `main` without an explicit plan update and
  repeated baseline proof.
- In an isolated qualification checkout, override both channels to the exact kernel
  candidate without committing or pushing and without semantically adapting the
  consumer.
- Build the consumer plugin and worker under the shared toolchain, run the external
  semantic profile, and run the actual Sage-backed notebook/E2E path.
- Read back worker and adapter provenance and compare both with the two declarations and
  candidate SHA.
- Record consumer commit, kernel commit, toolchain, dependency resolutions, runtime
  identities, conformance result, Sage/Jupyter result, and before/after consumer
  worktree state.
- After publication, land a second direct-to-main consumer dependency transaction that
  pins both the Lake worker and `just setup` adapter URL to the exact qualified release
  commit. Retain `v1.1.0` as human-readable release evidence, not as a floating resolver,
  and repeat the clean proof.

Acceptance requires the real consumer runtime and an unchanged candidate-qualification
worktree. A metadata edit, clean status alone, or kernel-side simulation is insufficient.

Stop on a required consumer semantic edit, divergent dependency identities, incompatible
toolchains, unverifiable provenance, a dirty candidate checkout, or failure of the
published-release repin.

## Workstream 7: CI and qualification composition

**Owner surfaces:** `.github/workflows/ci.yml`, repository-owned proof recipes, and
release qualification.

**Before:** worker, installed-kernelspec, frontend, and local sandbox checks exist, but
CI does not compose the external-plugin, clean-install, provenance, compatibility,
consumer, live-protection, or exact-release claims.

**After:** the four fixed required checks report distinct failure claims while reusing
builds and fixtures where safe:

- `worker (mathlib-free gate)`;
- `NbDsl + kernel round-trip + e2e`;
- `jupyterlab extension`; and
- `compatibility + external consumer`.

Required claim families:

1. mathlib-free worker build and directed Worker/plugin dependency boundary;
2. preserved worker/adapter protocol and installed-kernelspec semantics;
3. shared NbDsl and external-plugin semantic laws;
4. adapter artifact and kernelspec installation in clean environments;
5. local-path and nested-Git/Lake resolution with executed-binary provenance;
6. frontend unit/build/wheel/install/activation, plus browser proof for changed behavior;
7. exact-candidate consumer build, external conformance, and Sage/Jupyter E2E;
8. authoritative-release projection, build/runtime agreement, and intentional mismatch
   rejection; and
9. exact release-head qualification, publication readback, and tag-target readback.

Implementation obligations:

- Compose expensive setup where it preserves independence, but emit claim-specific
  outcomes and revision identities.
- Keep existing bare-worker and installed-kernelspec coverage or demonstrably equivalent
  real-boundary proof. Do not replace it with the smaller conformance law set.
- Keep the local bubblewrap check unless its existing owner deliberately changes; hostile
  notebook certification remains outside this programme.
- Make required checks deterministic with immutable external inputs. Do not qualify
  floating consumer or kernel refs.
- Bind all evidence to the commit and artifacts tested. A rerun on the actual release
  head is mandatory after any tree change.
- Keep the four status names stable and aggregate claim-specific steps inside them. A
  required aggregate fails if any owned claim is absent, skipped, or inconclusive.
- Add a tag-triggered publication job that consumes only artifacts rebuilt from and
  attested to the qualified `v1.1.0` target. It must not reuse unbound PR artifacts.

A green omnibus exit code is not enough. A reviewer must be able to identify which
runtime, installation, packaging, consumer, compatibility, or release claim failed.

## System-level proof matrix

| Claim | Real boundary | Required observation | False positive rejected |
| --- | --- | --- | --- |
| Semantic transaction | Real worker and plugin | Structured pre/post environment relations for success, error, and cancellation | Status strings, mocks, copied registries |
| Recovery | Forced replay and real process death through production client | Reconstructed committed semantic observation in active REPL/document mode | Calling a recovery helper directly |
| Isolation and queries | Two independent environments plus completion/inspection | Object visible only in the registering environment and its queries | Global registry or profile hard-coding |
| Control isolation | Dedicated descriptors and independent frame decoder | Correlated typed frames; adversarial output remains output | Using production codec on both sides |
| Jupyter semantics | Installed kernelspec via Jupyter client | Replies and IOPub from real adapter, worker, Lean, and plugin | Direct kernel/helper calls |
| Clean resolution | Empty Python/Jupyter env and minimal clean Lean projects | Executed worker identity for both dependency layouts | `find_worker_exe` unit result or path string |
| Frontend release | Built wheel installed into clean JupyterLab 4 | Wheel contents, discovery, activation; rendered inspection if changed | Node tests or build success alone |
| External consumer | Immutable clean checkout and real Sage/Jupyter path | Both declarations, runtime identities, conformance, E2E, unchanged candidate tree | Consumer metadata or kernel simulation |
| Compatibility | `release.toml`, generated projections, build provenance, artifacts, runtime, and negative case | One-way derivation plus deliberate mismatch rejection | Parallel hand-edited record, record existence, or source grep |
| Governance | Live GitHub API readback | Active PR/CI/no-force/no-delete rules | YAML or policy prose |
| Release | Exact-head CI, GitHub/PyPI/npm readback, published tag, and consumer repin | Artifact hashes, registry versions, tag-to-commit equality, and post-release downstream runtime proof | Merge, tag creation, or one-channel publication alone |

Evidence records must state the tested commit, immutable external commits, toolchain,
artifact identities, and observed result. They support the implementation claim; they
do not become a parallel source of product requirements or completion.

## Non-goals

- Hostile-notebook certification or a broader sandbox-security programme.
- Replacement or redesign of the opt-in bubblewrap feature.
- Exhaustive browser regression when frontend behavior is unchanged.
- A standalone public plugin SDK or separate conformance repository before a second
  independent external DSL needs one.
- Mandatory human approval counts without a real second reviewer.
- Moving, deleting, or reusing the historical broad `v1` tag.
- Semantic adaptation of `lean-cas-dsl` in candidate qualification.
- Snapshot garbage collection.
- Expected-type-aware completion beyond current environment/dot behavior.
- Making every currently uncacheable Lean state cacheable.
- NbDsl predicate iso-invariance or a free-group transport.
- Resolution of the mixed console/document recovery ceiling.
- Rewriting the established Lean-worker/Python-adapter/JupyterLab ownership split.

These exclusions do not permit loss of current runtime behavior or omission of generic
and external compatibility proof.

## Stop conditions

Stop the affected workstream and report the concrete blocker when:

1. either plugin cannot produce the fixed structured observation contract through
   plugin API v1;
2. the candidate requires a semantic consumer edit;
3. worker and plugin cannot share the declared Lean toolchain;
4. either dependency layout cannot identify and execute its intended worker;
5. worker and adapter provenance cannot be matched to one immutable source;
6. clean installation depends on undeclared developer or service state;
7. the frontend wheel cannot contain and activate the built extension;
8. the qualified release head changes;
9. any generated projection, artifact, runtime identity, provenance record, registry
   version, or tag disagrees with `release.toml` and the qualified commit;
10. the published consumer repin fails the clean Sage-backed boundary;
11. live branch protection cannot be read back;
12. trusted publication cannot be configured for PyPI or npm; or
13. a completion argument has only tests, records, logs, issue states, or metadata and
    lacks the corresponding runtime, clean-install, consumer, and release observations.

Do not route around a stop by adding a fallback, weakening an observation, filtering a
diagnostic, substituting a helper test, or relabeling the obligation as future work.

## Completion condition

The programme is complete only when all of the following are true:

- The one programme-sized `lean-jupyter-kernel` PR contains every kernel-repository
  implementation and proof-composition change in this plan.
- The exact release target preserves existing core behavior and passes both semantic
  profiles, clean adapter/kernelspec installation, both worker dependency layouts,
  extension artifact installation/activation, release-projection and provenance checks,
  and exact candidate consumer qualification.
- `v1.1.0` resolves to that exact qualified target; GitHub exposes the two wheels, two
  sdists, npm tarball, checksums, and provenance; PyPI exposes both Python distributions;
  npm exposes `jupyterlab_nbdsl@1.1.0`; and all package, toolchain, API, wire, commit,
  tag, adapter, and worker identities agree.
- Live repository protection is active and verified.
- `lean-cas-dsl` consumes the published immutable release through both dependency
  channels and repeats its clean build, external semantic conformance, real Sage-backed
  Jupyter E2E, and runtime-provenance proof.

No partial green suite, merged PR, compatibility file, release artifact, closed issue,
or count of completed workstreams satisfies this condition by itself.

## Progress and review use

Track progress against the seven owner workstreams and the strict release/consumer tail.
Mark a workstream complete only when its before/after behavior and real proof boundary
are both satisfied on the current candidate. If a task is partly complete, record the
proved portion and leave the remaining behavior explicit.

At every PR-head change that can affect behavior or identity:

- invalidate superseded qualification evidence;
- rerun the affected boundary on the new head;
- regenerate and check every release projection and invalidate any provenance object
  bound to the previous head; and
- keep unresolved stop conditions visible in the draft PR.

## Public traceability

The kernel merge completes the release-control, semantic-conformance, clean-install, and
candidate-qualification work units:

Closes #2

Closes #3

Closes #4

Closes #6

The baseline consumer transaction, release publication, and post-release consumer
transaction land outside the kernel PR and close only after their own real proof:

Refs #5

Refs #7

Refs #8
