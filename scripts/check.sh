#!/usr/bin/env bash
# Full verification: Lean build + QC + worker protocol + Jupyter E2E.
set -euo pipefail
cd "$(dirname "$0")/.."

just cache
just test   # lake build + lean-no-sorry + worker protocol roundtrip

if [ ! -x .venv/bin/pytest ]; then
  uv venv .venv
  uv pip install -p .venv/bin/python -e 'nbdsl_kernel[test]'
fi
.venv/bin/python -m nbdsl_kernel.install --project "$PWD/dsls/nbdsl"
.venv/bin/pytest nbdsl_kernel/tests/test_e2e.py -q
python3 nbdsl_kernel/tests/sandbox_check.py
