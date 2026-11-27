# lean-jupyter-kernel Constitution

This repository builds a Jupyter kernel that sends notebook cells to a persistent Lean worker.
A language such as the CAS of lean-cas-dsl enters through the plugin boundary. This document is
the permanent authority of the repository. The README, `docs/` and `AGENTS.md` describe the
product and point here for rules. Where one of them disagrees with an article, the article holds
and the document is corrected.

External sources cited by identifier:

| ID | Source |
| --- | --- |
| [K] | lean-cas-dsl constitution v5.0.0, `.specify/memory/constitution.md` on `main` |
| [KS] | lean-cas-dsl `specs/001-categorical-research-language/spec.md` (User Stories 7 and 8, FR-034 to FR-038, FR-043, FR-140, SC-010, SC-011, SC-016) |
| [NS] | lean-cas-dsl `specs/001-categorical-research-language/contracts/notebook-session.md` (notebook session contract v2) |
| [KT] | lean-cas-dsl `specs/001-categorical-research-language/tasks.md` (the notebook unit: T083 to T093, T098, T099 and T347; T127 for the application log; T153 for the notebook launch; T105 for the toolchain port) |

## Core Principles

### J1. Cell text reaches Lean verbatim

Python never tokenizes, parses or interprets a character of a cell. The Python kernel does
transport and rendering only. The kernel's completion, inspection, diagnostics and syntax
completeness are answers of the Lean worker, not of Python. (`docs/architecture.md:9`, `:19-20`;
`README.md:3-6`.)

In the editor of a Lean notebook, a separate channel to the Lean language server MAY give the goal
state, hover, diagnostics, completion and navigation of uncommitted cell text. That channel never
answers a kernel request (J5), sends nothing to the worker, and is off for a plugin whose
elaboration computes outside Lean: no cell text of the CAS reaches a language server ([KS] User
Story 7, scenario 2; FR-035).

### J2. The worker is language-agnostic; a language enters through the plugin boundary

Nothing under `worker/` imports a language module. The commit gate fails on such an import. A
language is a plugin, and its manifest is one Lean module name. A plugin keeps its semantic state
in the `Environment`, never in a module-level `IO.Ref`. A plugin never writes to stdout framing
or to the control file descriptors. (`docs/plugins.md:3-5`, `:11-13`, `:28-29`, `:38`;
`worker/README.md:9`.)

The CAS enters only as the plugin that lean-cas-dsl supplies. Its public session is
`CasRuntime.KernelSession`. The worker and the client carry its requests and results; they select
no meaning, route, provider or choice. A front end MUST NOT add a route preference, supply a
missing categorical choice or turn a selection error into a different query ([NS] preamble).

NbDsl (`dsls/nbdsl/`) is the reference plugin of this repository. It is a transport specimen. Its
own semantics (for example the shortest-path search of `#via`, `docs/dsl.md:69-76`) is not a model
of the CAS semantics and binds no other plugin.

### J3. Results stay usable in later cells

A committed cell result stays usable in every later cell that executes on a snapshot that
contains it ([K] C8). A cell executes on an explicit committed parent snapshot. The parent is a
snapshot of the live worker; a missing parent gives `unavailable/snapshot_unavailable`, never
execution of preceding cells. Equal source text, an equal hash or a repeated transport ID is not
the same occurrence ([NS] §1, §3.1). Saved cell text and saved output are document data, not
live computational state.

### J4. Failure and lifecycle behaviour cannot alter the selected question

No retry, replay, restart, migration, cache restoration or fallback happens without an explicit
user action ([K] C13 and its policy "Retry and migration"). In particular:

- Worker loss never restores a session cache, replays a prefix or rebinds old tokens into a new
  process. An explicit restart starts a fresh worker with a fresh nonce and no replay ([NS] §1).
- A failed or cancelled cell keeps its parent snapshot and publishes no output, no reference and
  no observation. A partial reply or a successful prefix of a failing cell is not success
  ([NS] §4).
- A closed or invalidated owner is never revived. A forced close invalidates its generation; a
  later use of a dependent reference is unavailable ([NS] §3.3).
- A request whose reply is lost after send is reported as `unavailable/connection_lost_after_send`
  with indeterminate execution. The client sends it again never ([NS] §3.1).
- A repeated transport ID is rejected with the source-free duplicate diagnostic. That diagnostic
  does not settle the original execution ([NS] §3.0).
- An explicit rerun is a fresh request with a fresh transport ID.

### J5. Inspection executes nothing

`inspect`, `complete` and `is_complete` read committed state only. They do not start or recover a
worker, elaborate candidate text, expand user macros, run `#eval`, run proof search, dispatch to
a CAS, call a lazy field or a provider, or call an extensible printer, delaborator or
documentation hook on a success path or an error path ([K] C15; [KS] FR-035; [NS] §3.2). Candidate
text only locates tokens. `is_complete` uses syntax inspection that runs no user extension. With
no compatible worker, `is_complete` answers `unknown`, and `inspect` and `complete` answer
unavailable.

### J6. Compatibility is a validated handshake before any source

The client validates the worker handshake before it serializes or sends candidate source of any
kind: protocol 2, a fresh process nonce, the eight notebook features, the frozen realization
profile hash and the matching `hello` acknowledgement ([NS] §2). An incompatible or
unacknowledged worker receives no source. Unknown majors, policies, modes, operations and control
fields are protocol errors; no downgrade and no executable fallback exists.

### J7. Mathematical display is automatic, once per event

A committed result renders automatically, with `text/latex` where the plugin supplies it and a
usable `text/plain` in the same MIME bundle. One result event is one display. A second plaintext
display under a rendered result is a defect. Backend, routing and timing diagnostics are shown
only on request. Required mathematical qualifications stay with the result ([K] policy "Default
mathematical display"; [KS] FR-038). The client deduplicates by batch and result ID, never by
execution again.

### J8. Typed wire; fail loudly

Every wire frame has a typed model. A malformed reply is a validation failure, and untyped
dictionaries do not circulate (`docs/architecture.md:96-97`). The protocol roundtrip suite is an
independent oracle: its frame codec stays separate from the client codec
(`docs/development.md:46`; `docs/protocol.md:3-5`).

### J9. One toolchain with the kernel

The worker executable and the plugin oleans come from the same Lean toolchain
(`docs/plugins.md:85-86`). This repository pins the Lean toolchain and, for `dsls/nbdsl`, the
Mathlib revision that lean-cas-dsl `main` pins for the research image (lean-cas-dsl `AGENTS.md`,
"Source location"; its `lean-toolchain` and `lake-manifest.json`). A change of that pin in
lean-cas-dsl is followed by the same change here, through a task of the task list.

## Engineering defaults

### E1. Test tiers

Tier 1 is the smallest set of tests that establishes correctness through the happy paths and
the branches that matter. It runs in seconds or minutes, and within 300 seconds on the
development host (the lean-cas-dsl loop limit). A slow tier 1 is a defect, repaired when it is
found. Tier 1 is: the mathlib-free worker build, the boundary check, the no-`sorry` scan of
`worker/`, strict mypy, the core-only protocol roundtrip, and the client tests that drive the
mathlib-free worker. Tier 2 adds the NbDsl build with Mathlib, the full roundtrip, the
end-to-end Jupyter suite, the clean install and the conformance journeys. Tier 3 adds consumer
qualification against lean-cas-dsl with a real `KernelSession`.

### E2. Test design

A test exercises externally observable behaviour of a user story end to end: a real notebook
cell through the installed kernel or the production client, through the real worker, with the
real plugin (the mathlib-free native session, NbDsl, or the CAS with `KernelSession`). Mocks,
tests of internal units and tests that bypass the user path are not admitted. Replies are matched
by `parent_header.msg_id` (`docs/development.md:61-63`). A test does not depend on the order of
other tests.

### E3. Contribution lessons

`CONTRIBUTING.md` records lessons from past mistakes as policies with stable alphanumeric IDs,
grouped by category. Each policy names a general class of contribution and, where possible, shows
a defective contribution beside its replacement. A new lesson gets a new ID; an ID is never
reused.

### E4. Feedback cadence

Feedback loops of ten minutes or more are minimized. The commit hook runs tier 1 only. Tiers 2
and 3 run at milestones: at a push, at the end of a batch of tasks, or at a handoff.

### E5. Platform scope

The product supports one platform: Linux in the shared math container. Another platform is
added only on explicit request.

### E6. Logging

The worker and the client write detailed application logs to a file, not to the notebook. For
each cell they record the request, the parent snapshot, the transaction, the outcome, the
commit or the failure, and the published batch ([KS] FR-043). Diagnostics shown to the user stay
opt-in (J7). Each test run writes a durable log that is kept in the repository under
`records/test-runs/`.

### E7. Timing history

Every test and every cell computation has a timing record with setup, fixtures, construction
and nested work, and with its run, revision, environment and input. The records are JSON lines
kept in the repository under `records/timing/`.

### E8. Timing triage

Optimization work is selected from a triage table of measured costs: operation, cost per call,
multiplying factors, aggregate cost, priority, proposed remedy and remaining measured cost. The
aggregate is the cost per call times every real multiplier. Optimization follows required
functionality, except repair of a slow tier 1 (E1).

### E9. Construction cost

Worker startup and session construction are close to instant relative to cell work. Expensive
work is deferred until a request demands it. When internal setup dominates, timing triage
applies.

## Roles and inputs

| Role | Authors in this repository | Inputs |
| --- | --- | --- |
| Kernel owner (K) | worker, client, kernel adapter, NbDsl, tests, documents, this constitution and the feature directory | [NS], [KS], [KT], this constitution, the repository documents |
| Independent assessor (I/A of lean-cas-dsl) | nothing here | builds of this repository at a named revision; runs lean-cas-dsl T094, T095, T102, T107 |
| CAS plugin author (lean-cas-dsl) | nothing here | the plugin contract `docs/plugins.md` and the protocol `docs/protocol.md` |

## Work order

The task list `specs/001-worker-protocol-2/tasks.md` governs execution. Its unchecked tasks
are executed in document order. A task that needs a capability of lean-cas-dsl names the kernel
task that supplies it; the contributor does that work in lean-cas-dsl and then returns. A change
of order is a committed edit of the task list that states its reason. The GitHub issue tree
(issue #1) records the programme; it does not order the work of a feature.

## Governance

This constitution supersedes the other documents of the repository. An amendment is a commit
that changes this file through the `speckit-constitution` skill and then brings the
specification, plan and task list into agreement through `speckit-specify`, `speckit-plan`,
`speckit-tasks` and `speckit-analyze`. Versions follow semantic versioning: MAJOR for a removed or
redefined article, MINOR for a new article or a material expansion, PATCH for wording. A review
of a change checks it against every article that the change touches.

**Version**: 1.1.1 | **Ratified**: 2026-11-25 | **Last Amended**: 2026-11-27
