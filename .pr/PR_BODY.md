# Intended result

Deliver the complete `v1 reliability and compatibility` programme through one branch and one review loop. This PR owns all seven implementation issues and remains draft until each issue's acceptance criteria has linked evidence.

This is deliberately one PR. The baseline and post-release `lean-cas-dsl` pin changes are coordinated direct-to-main evidence transactions in that repository; they are not separate review units and do not remove `#5` or `#8` from this PR's completion claim.

## Scope

Included:

- merge and release governance plus the canonical compatibility record;
- semantic conformance against NbDsl and lean-cas-dsl;
- clean installation, dependency resolution, and JupyterLab activation proof;
- immutable baseline and post-release consumer pins;
- exact-candidate clean-consumer qualification;
- publication of the exact qualified governed release.

Excluded:

- sandbox certification for untrusted notebooks;
- exhaustive frontend regression unless implementation changes frontend behavior;
- unrelated cleanup, compatibility shims, or independent pin-update PRs.

## GitHub tracking

- Root ledger: Refs #1
- Programme grouping: Refs #9
- Milestone: `v1 reliability and compatibility`
- Authoritative agent-memory plan: `PLAN-LEAN-NOTEBOOK-SINGLE-PR-DELIVERY`

Closes #2

Closes #3

Closes #4

Closes #5

Closes #6

Closes #7

Closes #8

## Execution plan

1. Establish `#2` governance and the canonical compatibility record so all later evidence has one identity owner.
2. In parallel, implement `#3` semantic conformance and `#4` clean installation and activation proof.
3. Land the direct baseline consumer pin for `#5` and record its immutable commit and clean-checkout evidence here.
4. Integrate the kernel work and qualify the exact candidate through the clean lean-cas-dsl boundary for `#6`.
5. Publish the governed exact-head release for `#7` only after candidate qualification is green.
6. Land the direct post-release consumer repin for `#8`, then rerun and record the clean-checkout proof.
7. Reconcile every claim below against its issue, preserve the qualified identity through merge, and only then mark this PR ready.

Parallel implementation does not create separate PR ownership.

## Completion invariants

- This PR owns whole claims for `#2` through `#8`; no issue is partially claimed, deferred, or reclassified outside the programme.
- Candidate evidence identifies the exact commit and compatibility record being proved.
- Any change to the release target invalidates prior candidate evidence and requires requalification.
- The release tag identifies the qualified target. The final merge must preserve that identity or repeat the proof against the merge result.
- Passing checks are receipts, not substitutes for issue-specific acceptance evidence.
- This PR stays draft while any claim-map item lacks implementation or evidence.

## Claim map

- [ ] [#2 — Establish lightweight merge and release governance](https://github.com/dzackgarza/lean-jupyter-kernel/issues/2)
  - Deliver the required ruleset or branch protection, compact correctness and integration CI, release policy, and canonical compatibility record.
  - Required evidence: live GitHub settings, workflow runs, and the issue-owned repository artifact.
  - Evidence: not yet recorded; this PR remains draft.

- [ ] [#3 — Add semantic plugin and session conformance](https://github.com/dzackgarza/lean-jupyter-kernel/issues/3)
  - Prove the issue's eight environment and session laws against both NbDsl and lean-cas-dsl through the production kernel path, including required invalid-nearby behavior.
  - Required evidence: exact identities, targeted commands, and production-path results.
  - Evidence: not yet recorded; this PR remains draft.

- [ ] [#4 — Prove clean kernel installation and worker resolution](https://github.com/dzackgarza/lean-jupyter-kernel/issues/4)
  - Prove supported-environment installation, dependency resolution, path and nested-Git behavior, kernelspec discovery, and JupyterLab activation from clean state.
  - Required evidence: clean-environment commands and results; an existing developer environment is not sufficient.
  - Evidence: not yet recorded; this PR remains draft.

- [ ] [#5 — Pin lean-cas-dsl to the current immutable kernel revision](https://github.com/dzackgarza/lean-jupyter-kernel/issues/5)
  - Land the synchronized immutable baseline pin directly on lean-cas-dsl `main` before candidate qualification.
  - Required evidence: consumer commit identity and clean-checkout result recorded here.
  - Evidence: not yet recorded; this PR remains draft.

- [ ] [#6 — Test a prospective kernel revision against a clean lean-cas-dsl checkout](https://github.com/dzackgarza/lean-jupyter-kernel/issues/6)
  - Test the exact candidate and governed compatibility identities through the real clean-consumer boundary.
  - Required evidence: candidate commit, consumer commit, environment identities, commands, and results. Evidence expires if the candidate changes.
  - Evidence: not yet recorded; this PR remains draft.

- [ ] [#7 — Publish the first governed v1.x release](https://github.com/dzackgarza/lean-jupyter-kernel/issues/7)
  - Release only the exact qualified target, update governed versions and release notes, and preserve the proof-bearing identity through final merge.
  - Required evidence: tag, release artifact, live checks, and identity reconciliation.
  - Evidence: not yet recorded; this PR remains draft.

- [ ] [#8 — Repin lean-cas-dsl after the governed kernel release](https://github.com/dzackgarza/lean-jupyter-kernel/issues/8)
  - After the governed release exists, land its immutable pin directly on lean-cas-dsl `main` and prove a clean consumer checkout.
  - Required evidence: post-release consumer commit and clean-checkout result recorded here before merge.
  - Evidence: not yet recorded; this PR remains draft.

## Automated and live gates

The existing `.github/workflows/ci.yml` remains the current automated gate. Work under `#2` may strengthen that workflow and configure the live GitHub ruleset. The claim map also requires the clean installation, semantic conformance, exact-candidate consumer, release, and post-release consumer boundaries specified by their owning issues.

Do not mark a claim complete from a green but irrelevant check.

## Stop rules

Stop and obtain direction if:

- satisfying the programme requires modifying vendored or upstream Lean code;
- the required public Lean plugin surface does not exist;
- release mechanics cannot preserve the exact qualified target;
- clean-environment proof contradicts the compatibility record;
- an issue's acceptance criteria would need to be weakened, reclassified, or moved outside this PR.

## Review focus

Review the PR as one programme-sized completion claim. Compare the implementation and evidence with all seven owning issues, with special attention to exact identity preservation across candidate qualification, release, merge, and both consumer pins.
