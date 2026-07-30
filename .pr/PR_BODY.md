# Reliable, compatible Lean notebooks: programme delivery plan

> Tier: workstream / organizational
> Parent plan: root / researcher-facing programme
> Externalized fit: the single programme-sized `lean-jupyter-kernel` draft PR; issues
> #2–#8 provide public traceability only
> Delivery constraint: every `lean-jupyter-kernel` code, packaging, CI, governance
> configuration, compatibility, and release-control change in this programme ships in
> this one PR

## Researcher-visible after-state

A researcher installs one exact v1.x release, selects a Lean project and plugin, and
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

One machine-readable compatibility identity connects the Lean toolchain, worker,
adapter, extension, plugin API, wire protocol, exact kernel commit, and exact tag.
Package declarations, runtime observations, downstream provenance, CI qualification,
and tag readback agree with that identity. Live `main` protection admits changes through
PRs and required CI and forbids force pushes and branch deletion.

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
- Milestone: the governed v1.x release; select the exact SemVer before editing governed
  release versions.
- Issues to close on merge: only requirements fully satisfied by the kernel PR at merge.
- Issues to reference: any issue whose release publication or downstream repin
  obligation remains open.
- Proof claimed by the PR: current-tree kernel behavior, clean packaging and
  installation, exact-candidate consumer qualification, compatibility consistency, and
  readiness of exact-head release controls.
- Proof completed after merge: qualification of the actual release commit, tag-to-commit
  readback, and consumer adoption of the published identity.

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
| Compatibility | Versions and toolchains are distributed across package files | One authoritative record validates every declaration and runtime identity and rejects mismatch |
| External consumer | Required synchronization and runtime proof are reported but unverified here | Both dependency channels name one immutable kernel; exact candidate and published release pass the real Sage/Jupyter boundary |
| Release | CI does not bind all claims to one exact release identity | The actual tag target passes exact-head qualification, the tag resolves to that commit, and the consumer adopts it |
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
- A repository-owned compatibility record, validator, negative mismatch proof, CI
  composition, release-head qualification, and live ruleset readback.
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

## Decisions that must be resolved at their owning boundary

These are implementation gates, not invitations to weaken the contract.

1. **Semantic observation boundary.** First attempt to express each plugin's
   discriminating observations through its own commands and structured MIME/replies. If
   the shared laws still cannot compare exact environment state, stop and decide the
   smallest generic public Worker/plugin observation surface. Any new public surface
   must receive an explicit plugin API version before the conformance runner depends on
   it.
2. **Runtime provenance shape.** Define one structured identity readback shared by the
   worker handshake/description, adapter, compatibility validator, installed-kernelspec
   proof, and consumer qualification. It must report the exact candidate or release
   commit rather than infer identity from a filesystem path.
3. **Exact v1.x SemVer.** Select the release version before changing governed package
   versions. The worker, Python adapter, npm package, frontend Python distribution,
   compatibility record, and intended tag must use that decision.
4. **Frontend artifact builder.** Select the standard JupyterLab 4 wheel build path that
   embeds the built labextension. Stop if the resulting wheel still depends on a source
   tree, pre-existing build output, or development link.
5. **Immutable consumer baseline.** Select and record the exact `lean-cas-dsl` commit
   against which both dependency channels, the Sage boundary, and external profile are
   understood before candidate overrides are added.
6. **Native GitHub ownership and protection.** Select the minimal native GitHub
   mechanism for substantive issue ownership and the compact required-check names.
   Do not require human approval while no second reviewer exists, and do not impose the
   ownership process on typo/routine maintenance.
7. **Release publication set.** Before tagging, name the package artifacts actually
   published under the governed identity. Do not claim a package channel that is not
   built, qualified, and read back.

Only decision 1 can block the semantic-conformance design. The other workstreams may
start in parallel, but none may cross its named decision gate.

## Execution graph

### Intrinsic dependency chain

1. Freeze the shared compatibility fields and resolve whether semantic observation
   changes the public plugin API.
2. Add structured semantic observations and runtime provenance.
3. Apply the shared semantic laws to NbDsl, then to an immutable external-plugin
   profile.
4. Prove compatible toolchain selection, both worker-resolution layouts, and clean
   adapter/kernelspec installation.
5. Reconcile extension versions, build the distributable wheel, and prove clean
   JupyterLab activation.
6. Synchronize the consumer's baseline worker and adapter identities at one immutable
   kernel source.
7. Qualify the exact kernel candidate against the immutable consumer without changing
   its worktree.
8. Validate all declarations and observations against the compatibility record and run
   the complete required-check composition on the exact PR head.
9. Merge the one kernel PR. Qualify the actual release commit again if its tree or
   commit differs from the qualified PR head.
10. Publish the exact tag only after exact-head qualification, then read back that the
    tag resolves to the qualified commit.
11. Update both consumer dependency channels to the published immutable identity and
    repeat clean consumer build, semantic conformance, Sage/Jupyter E2E, and provenance
    proof.

Steps 7–11 are strict. PR checks against an earlier commit do not authorize tagging a
different commit, and publication does not authorize declaring completion before the
consumer repin passes.

### Safe parallel work inside the one PR

After the compatibility fields and affected API version are fixed:

- Lean semantic observation and shared-law design can proceed beside adapter provenance
  and clean-install fixtures.
- Frontend version reconciliation and distributable-wheel work can proceed beside the
  worker/adapter work when they consume the same frozen SemVer.
- Live ruleset configuration/readback design can proceed beside code implementation
  once required check identities are known.
- Consumer baseline synchronization can proceed beside kernel conformance work, but
  candidate qualification waits for both.
- CI composition can begin with existing proof families, but required status and
  release claims wait for the real new boundary jobs.

Every parallel branch integrates back into the same PR. The compatibility validator,
runtime identity, and claim-specific CI output are the integration contracts.

## Workstream 1: Lean worker semantic transaction and recovery

**Owner surfaces:** `worker/Worker.lean`, `worker/Worker/Frontend.lean`,
`worker/Worker/Protocol.lean`, `worker/Worker/SessionCache.lean`,
`worker/Worker/Query.lean`, and `worker/Worker/Output.lean`.

**Before:** snapshot atomicity, replay/cache behavior, completion, inspection, and output
isolation exist, but proof is coupled to NbDsl examples and no governed compatibility
identity joins the worker to the adapter and release.

**After:** the worker exposes enough structured, plugin-neutral observation and identity
to prove the same transaction and recovery laws for both profiles without importing
either plugin.

Implementation obligations:

- Preserve the selected-parent transaction in `handleExecute`: success commits the
  exact candidate; error and cooperative cancellation return the unchanged parent.
- Define structured observations that discriminate environment content, registered
  semantic objects, completion, inspection, replay, restart, and isolation. Keep
  plugin-specific registry commands in profiles rather than adding their schema to the
  worker.
- Add a real mid-command cancellation checkpoint case and a real process-death case.
  Drive recovery through the production client path in the appropriate REPL/document
  mode.
- Make the worker's toolchain, package/API/wire versions, and exact source identity
  available through the governed ready/description boundary.
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

Stop if meaningful observation requires an unversioned public plugin surface, if
recovery requires a non-production path, or if a profile-specific registry leaks into
the worker.

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
- Propagate structured worker and adapter provenance into the Jupyter/runtime result and
  compatibility checks.
- Keep Pydantic validation at the protocol boundary. Do not turn malformed or
  incompatible frames into success-shaped replies.

Acceptance:

- Each clean project starts the binary owned by its declared dependency graph, not one
  found in the source checkout or system.
- Runtime worker identity, adapter identity, selected prelude, and toolchain agree with
  the compatibility record.
- Installed-kernelspec observations preserve all existing execution, interrupt,
  completion, inspection, MIME, init, cache/replay, and document-mode obligations.

Stop on undeclared checkout state, an unresolved or ambiguous worker, toolchain
disagreement, or provenance that can only be inferred from a path.

## Workstream 3: plugin contract and shared semantic conformance

**Owner surfaces:** the kernel-owned conformance runner and result model,
`dsls/nbdsl/` as the reference profile, and an immutable `lean-cas-dsl` checkout as the
external profile.

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
- Keep profile data declarative and discriminating: immutable plugin source,
  package/prelude selection, commands, cancellation point, observations, and expected
  semantic relationships.
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

**After:** npm and Python metadata share the governed SemVer; the built wheel contains
the labextension, installs in clean JupyterLab 4, and activates without a development
link.

Implementation obligations:

- Reconcile npm `1.0.0` and Python `0.1.0` under the selected v1.x identity rather than
  validating either disagreement.
- Add the standard artifact build that places the compiled extension into the Python
  wheel and does not consume stale developer output.
- Inspect wheel contents, install that wheel into a clean JupyterLab 4 environment, and
  verify extension discovery and activation.
- Preserve language registration, document comm synchronization, stale-cell classes,
  and NbDsl path MIME validation/rendering.
- Retain node tests for pure functions. If this PR changes browser-visible behavior,
  launch real JupyterLab with the built artifact, render the affected notebook state,
  inspect it, and retain revision-tied evidence.

Acceptance distinguishes build, artifact contents, clean activation, and visual
adequacy. A successful TypeScript build proves none of the latter three by itself.

Stop if the wheel requires `labextension develop`, a source symlink, pre-existing build
output, or an undeclared service environment.

## Workstream 5: compatibility identity, governance, and release controls

**Owner surfaces:** one new machine-readable compatibility record; Lean, Python, and
frontend package declarations; worker/adapter runtime identity; CI release controls;
and the live GitHub repository ruleset.

**Before:** owned packages mostly declare `1.0.0`, frontend Python declares `0.1.0`,
wire version `1` is embedded in the worker, and no record binds these values to one
commit and tag.

**After:** one record authoritatively names:

- Lean toolchain;
- worker package SemVer;
- Python adapter SemVer;
- JupyterLab npm/Python SemVer;
- plugin API compatibility version;
- wire protocol version;
- exact kernel commit; and
- exact SemVer tag.

Implementation obligations:

- Choose a machine-readable schema with exact, bounded fields. Validate every owned
  declaration and runtime readback against it.
- Make development drift fail before release. Prove the validator rejects one
  deliberately inconsistent governed value.
- Inject or derive commit identity at build time without permitting an unknown/fallback
  release identity.
- Treat governed version changes as release work in this PR, not routine independent
  package bumps.
- Configure live `main` protection for PR admission, the compact required-check set, no
  force pushes, and no deletion. Read back the active rules from GitHub.
- Apply a native ownership route to substantive programme issues while exempting typo
  and routine maintenance. Do not build a parallel issue-state system.
- Qualify the exact release commit after merge if it differs from the qualified PR head.
  Publish the tag only after that run succeeds, then read back tag-to-commit equality.

Acceptance requires agreement among source declarations, built artifacts, runtime
observations, downstream provenance, CI revision, record commit, and tag target.

Stop if live rules cannot be read back, the release head changes, a package/runtime
identity disagrees, or the tag does not resolve to the qualified commit.

## Workstream 6: external `lean-cas-dsl` integration

**Owner boundary:** kernel qualification orchestration in this PR; dependency updates
and the real Sage-backed notebook boundary in the separate consumer repository.

**Before:** the required two-channel alignment and Sage-backed proof are reported needs,
not established facts in this plan.

**After:** one immutable consumer baseline resolves its Lake worker dependency and
Python adapter dependency to the same kernel identity. Qualification can replace both
with the exact candidate SHA ephemerally, prove the candidate, and leave the consumer
unchanged. After publication, the consumer commits both channels to the release identity
and repeats the proof.

Implementation obligations:

- Freeze an immutable consumer commit before treating its dependency layout or commands
  as facts.
- Establish a clean baseline in which both channels agree before testing an override.
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
- After tag publication, make the normal consumer-repository change that adopts the
  immutable release in both channels and repeat the clean proof.

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
consumer, live-governance, or exact-release claims.

**After:** a compact required set reports distinct failure claims while reusing builds
and fixtures where safe.

Required claim families:

1. mathlib-free worker build and directed Worker/plugin dependency boundary;
2. preserved worker/adapter protocol and installed-kernelspec semantics;
3. shared NbDsl and external-plugin semantic laws;
4. adapter artifact and kernelspec installation in clean environments;
5. local-path and nested-Git/Lake resolution with executed-binary provenance;
6. frontend unit/build/wheel/install/activation, plus browser proof for changed behavior;
7. exact-candidate consumer build, external conformance, and Sage/Jupyter E2E;
8. compatibility-record agreement and intentional mismatch rejection; and
9. exact release-head qualification and tag-target readback.

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
| Compatibility | Record, declarations, artifacts, runtime, and negative case | Complete equality plus deliberate mismatch rejection | Record existence or source grep |
| Governance | Live GitHub API readback | Active PR/CI/no-force/no-delete rules | YAML or policy prose |
| Release | Exact-head CI, published tag, and consumer repin | Tag-to-commit equality and post-release downstream runtime proof | Merge, tag creation, or publication alone |

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
- Issue ceremony for typo or routine maintenance.
- A floating or broad `v1` tag.
- Semantic adaptation of `lean-cas-dsl` in candidate qualification.
- Snapshot garbage collection.
- Expected-type-aware completion beyond current environment/dot behavior.
- Making every currently uncacheable Lean state cacheable.
- NbDsl predicate iso-invariance or a free-group transport.
- Resolution of the mixed console/document recovery ceiling.
- Preservation of unsupported internal compatibility paths.
- Rewriting the established Lean-worker/Python-adapter/JupyterLab ownership split.

These exclusions do not permit loss of current runtime behavior or omission of generic
and external compatibility proof.

## Stop conditions

Stop the affected workstream and obtain the named maintainer, API, or release decision
when:

1. meaningful plugin state cannot be observed without a public API change;
2. the candidate requires a semantic consumer edit;
3. worker and plugin cannot share the declared Lean toolchain;
4. either dependency layout cannot identify and execute its intended worker;
5. worker and adapter provenance cannot be matched to one immutable source;
6. clean installation depends on undeclared developer or service state;
7. the frontend wheel cannot contain and activate the built extension;
8. the qualified release head changes;
9. any governed declaration, artifact, runtime identity, record, or tag disagrees;
10. the published consumer repin fails the clean Sage-backed boundary;
11. live branch protection cannot be read back; or
12. a completion argument has only tests, records, logs, issue states, or metadata and
    lacks the corresponding runtime, clean-install, consumer, and release observations.

Do not route around a stop by adding a fallback, weakening an observation, filtering a
diagnostic, substituting a helper test, or relabeling the obligation as future work.

## Completion condition

The programme is complete only when all of the following are true:

- The one programme-sized `lean-jupyter-kernel` PR contains every kernel-repository
  implementation and proof-composition change in this plan.
- The exact release target preserves existing core behavior and passes both semantic
  profiles, clean adapter/kernelspec installation, both worker dependency layouts,
  extension artifact installation/activation, compatibility validation, and exact
  candidate consumer qualification.
- The governed v1.x tag resolves to that exact qualified target, and all package,
  toolchain, API, wire, commit, tag, adapter, and worker identities agree.
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
- update the decision log with any API, SemVer, consumer baseline, or release choice;
  and
- keep unresolved stop conditions visible in the draft PR.

## Public traceability

While the PR is draft, reference #2, #3, #4, #5, #6, #7, and #8. Add closing keywords
only when the issue's full requirement is satisfied by merge; retain a reference when
post-merge release or consumer-adoption proof remains.
