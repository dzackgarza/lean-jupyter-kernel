#!/usr/bin/env bash
# Core verification: Lean build + QC + worker protocol + Jupyter E2E.
set -euo pipefail

cd "$(dirname "$0")/.."

# Fail closed instead of running two full checks concurrently. The installed
# notebook workers are intentionally large, and overlapping checks turn a
# valid single-run memory budget into swap and disk thrashing.
export LEAN_NUM_THREADS=1
check_lock="${NBDSL_CONFORMANCE_LOCK:-${TMPDIR:-/tmp}/nbdsl-conformance-${UID}.lock}"
export NBDSL_CONFORMANCE_LOCK="$check_lock"
exec 9>"$check_lock"
if ! flock -n 9; then
  echo "another nbdsl worker-heavy check is already running: $check_lock" >&2
  exit 2
fi

if [ ! -f dsls/nbdsl/.lake/packages/mathlib/.lake/build/lib/lean/Mathlib/Init.olean ]; then
  just cache
fi
just test   # lake build + lean-no-sorry + worker protocol roundtrip

if [ ! -x .venv/bin/pytest ]; then
  uv venv .venv
  uv pip install -p .venv/bin/python -e 'nbdsl_kernel[test]'
fi
.venv/bin/python -m nbdsl_kernel.install --project "$PWD/dsls/nbdsl"
.venv/bin/pytest nbdsl_kernel/tests/test_e2e.py -q
