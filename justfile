# lean-jupyter-kernel — POC: a greenfield Lean-elaborated DSL running as a Jupyter kernel.
#
# Components: nbdsl/ (Lean package — DSL library NbDsl + persistent worker
# executable nbdsl_worker, built by lake under the pinned v4.32.0 toolchain)
# and nbdsl_kernel/ (Python ipykernel adapter). Lake owns compilation;
# language-level QC law delegates to the global gate
# (~/ai-review-ci/justfiles/lean.just).
#
# Not adopted: lean-axiom-audit — the DSL's abstract-object command will
# legitimately emit axioms in example modules, so an axiom audit needs a
# repo-supplied budget first (revisit when the worker ships proof-status output).

set dotenv-load := true

# No ai_review_ci_* contract stanza: this is a polyglot monorepo (Lean +
# Python + TS) and doctor's profiles demand exclusive whole-repo delegation
# (declaring "python" would be a false contract). The Python slice still runs
# the global mypy gate below. Upstream gap: ai-review-ci#353.

# Show available recipes
default:
    @just --list

# Fetch Mathlib's prebuilt compilation cache
cache:
    @cd dsls/nbdsl && lake exe cache get

# Build the core worker package and the reference DSL plugin
build:
    @cd worker && lake build nbdsl_worker
    @cd dsls/nbdsl && lake build NbDsl

# Run the full repository QC gate
test: build
    @python3 scripts/release_projection.py check
    @just -f ~/ai-review-ci/justfiles/lean.just -d worker lean-no-sorry
    @just -f ~/ai-review-ci/justfiles/lean.just -d dsls/nbdsl lean-no-sorry
    @! grep -rn '^import NbDsl' worker/ --include='*.lean' || \
        { echo 'BOUNDARY: the core must never import DSL modules'; exit 1; }
    @just -f ~/ai-review-ci/justfiles/python.just -d nbdsl_kernel _mypy
    @python3 nbdsl_kernel/tests/roundtrip.py

# Interpreter for the recipes needing the kernel package installed. CI
# installs into the job python; locally: `just python=.venv/bin/python …`.
python := "python3"

# Semantic plugin conformance (#3): the same laws against the in-repo
# reference plugin. Needs the kernel package installed (jupyter_client, a
# kernelspec) — like the e2e suite, it runs in CI rather than the local gate.
conformance:
    @{{python}} conformance/runner.py conformance/nbdsl.toml

# …and against an EXTERNAL plugin. Point CONFORMANCE_CAS_DSL at a clean
# checkout; the profile falls back to a sibling working tree.
conformance-external:
    @{{python}} conformance/runner.py conformance/lean-cas-dsl.toml

[private]
test-commit: test

# Run the CI quality gate
test-ci: test

[private]
test-push: test-ci
