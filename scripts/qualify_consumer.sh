#!/usr/bin/env bash
# Exact-candidate consumer qualification (issue #6).
#
# Clone the frozen lean-cas-dsl baseline, pin both kernel dependency channels
# to the candidate SHA, build + run the consumer Sage/Jupyter gate, run the
# external-plugin semantic journeys, and refuse any semantic consumer edit.
#
#   scripts/qualify_consumer.sh <candidate-kernel-sha> [workdir]
#
# Optional: KERNEL_GIT_URL (default GitHub), MATHLIB_SEED, AI_REVIEW_CI_SHA
# (provisioned by CI for the consumer's just test gate).

set -euo pipefail

KERNEL_REPO="$(cd "$(dirname "$0")/.." && pwd)"
CANDIDATE="${1:?usage: qualify_consumer.sh <candidate-kernel-sha> [workdir]}"
WORKDIR="${2:-$(mktemp -d /tmp/consumer-qualification-XXXXXX)}"
export LEAN_NUM_THREADS=1
export NBDSL_CONFORMANCE_LOCK="${NBDSL_CONFORMANCE_LOCK:-${TMPDIR:-/tmp}/nbdsl-conformance-${UID}.lock}"

[[ "$CANDIDATE" =~ ^[0-9a-f]{40}$ ]] || {
  echo "qualification: candidate must be a 40-hex commit" >&2
  exit 1
}

# Frozen baseline — keep in sync with conformance/test_semantic.py LEAN_CAS_DSL.
CONSUMER_URL="https://github.com/dzackgarza/lean-cas-dsl"
BASELINE="4c6fedafccfe77af80ac632efa780e967d726c14"

echo "== qualification: consumer $BASELINE  candidate kernel $CANDIDATE =="
CO="$WORKDIR/lean-cas-dsl"
git clone --quiet "$CONSUMER_URL" "$CO"
git -C "$CO" switch --quiet --detach "$BASELINE"

if [ -n "${MATHLIB_SEED:-}" ] && [ -d "$MATHLIB_SEED" ]; then
  mkdir -p "$CO/.lake/packages"
  git clone --quiet "$MATHLIB_SEED" "$CO/.lake/packages/mathlib"
  git -C "$CO/.lake/packages/mathlib" remote set-url origin \
    https://github.com/leanprover-community/mathlib4.git
fi

KERNEL_GIT_URL="${KERNEL_GIT_URL:-https://github.com/dzackgarza/lean-jupyter-kernel}"
python3 - "$CO" "$CANDIDATE" "$KERNEL_GIT_URL" <<'EOF'
import re, sys
from pathlib import Path
co, sha, url = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
rewrites = (
    ("lakefile.lean",
     r'"https://github\.com/dzackgarza/lean-jupyter-kernel"\s*\n?\s*@ "([0-9a-f]{40})" / "worker"',
     f'"{url}"\n    @ "{sha}" / "worker"'),
    ("justfile",
     r'git\+https://github\.com/dzackgarza/lean-jupyter-kernel@([0-9a-f]{40})#subdirectory',
     f'git+{url}@{sha}#subdirectory'),
)
for name, pat, repl in rewrites:
    f = co / name
    new, n = re.subn(pat, repl, f.read_text())
    if n != 1:
        sys.exit(f"{name}: expected exactly one pinned kernel dependency, found {n}")
    f.write_text(new)
    print(f"override: {name} -> {url} @ {sha}")
EOF

(cd "$CO" && lake update nbdsl-worker >/dev/null)
RESOLVED=$(python3 -c "import json; m=json.load(open('$CO/lake-manifest.json')); print([p['rev'] for p in m['packages'] if p['name'].strip('«»')=='nbdsl-worker'][0])")
[ "$RESOLVED" = "$CANDIDATE" ] || {
  echo "lake manifest resolved $RESOLVED != candidate" >&2
  exit 1
}

(cd "$CO" && just build && just setup && just test) 2>&1 | tee "$WORKDIR/consumer-gate.log"
grep -q "passed" "$WORKDIR/consumer-gate.log"

# External Journeys 2–5 against this checkout's kernelspec/venv.
export CONFORMANCE_CAS_DSL="$CO"
"$CO/.venv/bin/python" -m pytest "$KERNEL_REPO/conformance/test_semantic.py" \
  -k 'lean-cas-dsl' --tb=short

# No semantic consumer edit: only the declared pin files may be dirty.
DIRTY=$(git -C "$CO" status --porcelain | awk '{print $NF}' | LC_ALL=C sort | tr '\n' ' ')
DECLARED="justfile lake-manifest.json lakefile.lean "
[ "$DIRTY" = "$DECLARED" ] || {
  echo "worktree carries more than the declared overrides" >&2
  echo "  declared: $DECLARED" >&2
  echo "  actual:   $DIRTY" >&2
  exit 1
}
[ "$(git -C "$CO" rev-parse HEAD)" = "$BASELINE" ] || {
  echo "checkout moved off baseline" >&2
  exit 1
}

python3 - "$WORKDIR" <<EOF
import json, sys
json.dump({
  "schema": 2,
  "consumer_commit": "$BASELINE",
  "candidate_kernel_sha": "$CANDIDATE",
  "lake_resolved_rev": "$RESOLVED",
  "consumer_gate": "passed",
  "external_journeys": "lean-cas-dsl",
}, open(sys.argv[1] + "/qualification-evidence.json", "w"), indent=2)
print("== QUALIFIED: evidence in", sys.argv[1] + "/qualification-evidence.json ==")
EOF
