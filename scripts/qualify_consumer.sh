#!/usr/bin/env bash
# Exact-candidate consumer qualification (issue #6).
#
#   scripts/qualify_consumer.sh <candidate-kernel-sha> [workdir]
#
# Pin both kernel channels to the candidate, build, run Sage roundtrip +
# Jupyter E2E + extension-boundary semantic tests. Owns the frozen baseline.

set -euo pipefail

KERNEL_REPO="$(cd "$(dirname "$0")/.." && pwd)"
CANDIDATE="${1:?usage: qualify_consumer.sh <candidate-kernel-sha> [workdir]}"
WORKDIR="${2:-$(mktemp -d /tmp/consumer-qualification-XXXXXX)}"
export LEAN_NUM_THREADS=1

[[ "$CANDIDATE" =~ ^[0-9a-f]{40}$ ]] || {
  echo "qualification: candidate must be a 40-hex commit" >&2; exit 1; }

CONSUMER_URL="https://github.com/dzackgarza/lean-cas-dsl"
BASELINE="4c6fedafccfe77af80ac632efa780e967d726c14"
KERNEL_GIT_URL="${KERNEL_GIT_URL:-https://github.com/dzackgarza/lean-jupyter-kernel}"

echo "== qualification: consumer $BASELINE  candidate $CANDIDATE =="
CO="$WORKDIR/lean-cas-dsl"
git clone --quiet "$CONSUMER_URL" "$CO"
git -C "$CO" switch --quiet --detach "$BASELINE"

if [ -n "${MATHLIB_SEED:-}" ] && [ -d "$MATHLIB_SEED" ]; then
  mkdir -p "$CO/.lake/packages"
  git clone --quiet "$MATHLIB_SEED" "$CO/.lake/packages/mathlib"
  git -C "$CO/.lake/packages/mathlib" remote set-url origin \
    https://github.com/leanprover-community/mathlib4.git
fi

python3 - "$CO" "$CANDIDATE" "$KERNEL_GIT_URL" <<'EOF'
import re, sys
from pathlib import Path
co, sha, url = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
for name, pat, repl in (
    ("lakefile.lean",
     r'"https://github\.com/dzackgarza/lean-jupyter-kernel"\s*\n?\s*@ "([0-9a-f]{40})" / "worker"',
     f'"{url}"\n    @ "{sha}" / "worker"'),
    ("justfile",
     r'git\+https://github\.com/dzackgarza/lean-jupyter-kernel@([0-9a-f]{40})#subdirectory',
     f'git+{url}@{sha}#subdirectory'),
):
    f = co / name
    new, n = re.subn(pat, repl, f.read_text())
    if n != 1:
        sys.exit(f"{name}: expected one kernel pin, found {n}")
    f.write_text(new)
EOF

(cd "$CO" && lake update nbdsl-worker >/dev/null)
RESOLVED=$(python3 -c "import json; m=json.load(open('$CO/lake-manifest.json')); print([p['rev'] for p in m['packages'] if p['name'].strip('«»')=='nbdsl-worker'][0])")
[ "$RESOLVED" = "$CANDIDATE" ] || { echo "lake resolved $RESOLVED != $CANDIDATE" >&2; exit 1; }

cd "$CO"
just build
just setup
python3 tests/roundtrip.py
.venv/bin/pytest tests/test_e2e.py -q

export CONFORMANCE_CAS_DSL="$CO"
"$CO/.venv/bin/python" -m pytest "$KERNEL_REPO/conformance/test_semantic.py" \
  -k 'casdsl' --tb=short

DIRTY=$(git -C "$CO" status --porcelain | awk '{print $NF}' | LC_ALL=C sort | tr '\n' ' ')
[ "$DIRTY" = "justfile lake-manifest.json lakefile.lean " ] || {
  echo "unexpected dirty paths: $DIRTY" >&2; exit 1; }
[ "$(git -C "$CO" rev-parse HEAD)" = "$BASELINE" ] || {
  echo "checkout moved off baseline" >&2; exit 1; }

echo "== QUALIFIED $CANDIDATE against $BASELINE =="
