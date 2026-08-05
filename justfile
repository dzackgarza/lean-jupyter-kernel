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

# Interpreter for the recipes needing the kernel package installed. CI
# installs into the job python; locally: `just python=.venv/bin/python …`.
python := "python3"
export LEAN_NUM_THREADS := "1"

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

# Build the core worker package and the reference DSL plugin.
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
    @JUPYTER_DATA_DIR="$(mktemp -d)"; export JUPYTER_DATA_DIR; \
      trap 'rm -rf "$JUPYTER_DATA_DIR"' EXIT; \
      uv run --isolated --no-project --with build --with pyyaml \
        --with-editable './nbdsl_kernel[test]' sh -c \
        'python -m nbdsl_kernel.install --project "$PWD/dsls/nbdsl" && \
         python -m pytest nbdsl_kernel/tests/test_worker_resolve.py \
           nbdsl_kernel/tests/test_identity.py \
           nbdsl_kernel/tests/test_restart.py \
           nbdsl_kernel/tests/test_inspect.py \
           nbdsl_kernel/tests/test_roundtrip_cleanup.py && \
         python -m pytest conformance/test_semantic.py -k nbdsl'

# Semantic plugin conformance (#3): Journeys 2–5 against the in-repo NbDsl
# case. The `test` gate runs the same pytest target inside its hermetic uv
# env above; this recipe is the entry for CI's "NbDsl semantic journeys"
# step and for manual runs, where {{python}} already has the kernel package.
[private]
_conformance:
    @{{python}} -m pytest conformance/test_semantic.py -k nbdsl

# The same journeys against lean-cas-dsl: point CONFORMANCE_CAS_DSL at a
# clean checkout, or the sibling ../lean-cas-dsl is used; skips if neither
# is present. Not part of any gate — it needs the external repo.
# Run the semantic journeys against a lean-cas-dsl checkout (skips if absent)
conformance-external:
    @{{python}} -m pytest conformance/test_semantic.py -k casdsl

[private]
test-commit: test

# Run the CI quality gate
test-ci: test

[private]
test-push: test-ci
