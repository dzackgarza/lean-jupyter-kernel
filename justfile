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
    @just -f ~/ai-review-ci/justfiles/lean.just -d worker lean-no-sorry
    @just -f ~/ai-review-ci/justfiles/lean.just -d dsls/nbdsl lean-no-sorry
    @! grep -rn '^import NbDsl' worker/ --include='*.lean' || \
        { echo 'BOUNDARY: the core must never import DSL modules'; exit 1; }
    @python3 nbdsl_kernel/tests/roundtrip.py

[private]
test-commit: test

# Run the CI quality gate
test-ci: test

[private]
test-push: test-ci
