#!/usr/bin/env bash
# Exact-candidate consumer qualification (issue #6, Workstream 6).
#
# In an EPHEMERAL clean checkout of the frozen lean-cas-dsl baseline, override
# both kernel dependency channels to the exact candidate kernel SHA, build the
# consumer, run its real Sage-backed gate (roundtrip + Jupyter E2E), run the
# full kernel-owned Journeys 2–5 proof, read back dependency + runtime
# provenance, and prove the checkout carries exactly the two declared
# overrides and nothing else. Nothing is committed or pushed; the consumer's
# semantics are never adapted.
#
#   AI_REVIEW_CI_SHA=<reviewed-commit> \
#     scripts/qualify_consumer.sh <candidate-kernel-sha> [workdir]
#
# The frozen baseline (repo + commit) is read from conformance/lean-cas-dsl.toml
# — the single owner of that fact. Evidence lands in
# <workdir>/qualification-evidence.json. Any failure is terminal (set -e); the
# stop rule is: do not adapt the consumer, report instead.

set -euo pipefail

KERNEL_REPO="$(cd "$(dirname "$0")/.." && pwd)"
CANDIDATE="${1:?usage: qualify_consumer.sh <candidate-kernel-sha> [workdir]}"
WORKDIR="${2:-$(mktemp -d /tmp/consumer-qualification-XXXXXX)}"
PROFILE="$KERNEL_REPO/conformance/lean-cas-dsl.toml"
AI_REVIEW_CI_SHA="${AI_REVIEW_CI_SHA:?qualification requires AI_REVIEW_CI_SHA}"
export LEAN_NUM_THREADS=1
export NBDSL_CONFORMANCE_LOCK="${NBDSL_CONFORMANCE_LOCK:-${TMPDIR:-/tmp}/nbdsl-conformance-${UID}.lock}"
[[ "$CANDIDATE" =~ ^[0-9a-f]{40}$ ]] || {
  echo "qualification: candidate must be a 40-hex commit"
  exit 1
}
[[ "$AI_REVIEW_CI_SHA" =~ ^[0-9a-f]{40}$ ]] || {
  echo "qualification: AI_REVIEW_CI_SHA must be a 40-hex commit"
  exit 1
}

read -r CONSUMER_URL BASELINE < <(python3 - "$PROFILE" <<'EOF'
import sys, tomllib
p = tomllib.loads(open(sys.argv[1], "rb").read().decode())
plug = p["plugin"]
print(plug["source"], plug["commit"])
EOF
)
case "$BASELINE" in *TBD*) echo "profile has no frozen baseline"; exit 1;; esac

echo "== qualification: consumer $BASELINE  candidate kernel $CANDIDATE =="
CO="$WORKDIR/lean-cas-dsl"
git clone --quiet "$CONSUMER_URL" "$CO"
git -C "$CO" switch --quiet --detach "$BASELINE"

# Optional: seed the mathlib package clone from a local repository so the
# ~300MB fetch doesn't ride the network (lake then fetches only the delta).
if [ -n "${MATHLIB_SEED:-}" ] && [ -d "$MATHLIB_SEED" ]; then
  mkdir -p "$CO/.lake/packages"
  git clone --quiet "$MATHLIB_SEED" "$CO/.lake/packages/mathlib"
  git -C "$CO/.lake/packages/mathlib" remote set-url origin \
    https://github.com/leanprover-community/mathlib4.git
  echo "mathlib seeded from $MATHLIB_SEED"
fi

# --- override both dependency channels to the exact candidate (ephemeral) ---
# KERNEL_GIT_URL lets CI point the consumer at the runner's own kernel
# checkout (file://$GITHUB_WORKSPACE) so pull-request merge commits — which
# are not fetchable from the public clone URL — still qualify exactly.
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
git -C "$CO" diff --binary -- \
  justfile lake-manifest.json lakefile.lean \
  > "$WORKDIR/expected-overrides.diff"
RESOLVED=$(python3 -c "import json; m=json.load(open('$CO/lake-manifest.json')); print([p['rev'] for p in m['packages'] if p['name'].strip('«»')=='nbdsl-worker'][0])")
[ "$RESOLVED" = "$CANDIDATE" ] || { echo "lake manifest resolved $RESOLVED != candidate"; exit 1; }

# --- consumer build + full real gate (Sage roundtrip + Jupyter E2E) ---
# `setup` requires the built worker (it installs the kernelspec against the
# exe), so build first — the same order the consumer's own gate uses.
(cd "$CO" && just build && just setup && just test) 2>&1 | tee "$WORKDIR/consumer-gate.log"
grep -q "passed" "$WORKDIR/consumer-gate.log"

# --- runtime provenance readback ---
PIP_COMMIT=$(python3 - "$CO" <<'EOF'
import json, sys
from pathlib import Path
site = next(Path(sys.argv[1], ".venv").glob("lib/python*/site-packages"))
info = next(site.glob("nbdsl_kernel-*.dist-info"))
print(json.loads((info / "direct_url.json").read_text())["vcs_info"]["commit_id"])
EOF
)
[ "$PIP_COMMIT" = "$CANDIDATE" ] || { echo "adapter installed from $PIP_COMMIT != candidate"; exit 1; }
WORKER_PKG="$CO/.lake/packages/nbdsl-worker"
WORKER_COMMIT=$(git -C "$WORKER_PKG" rev-parse HEAD)
[ "$WORKER_COMMIT" = "$CANDIDATE" ] || { echo "worker checkout at $WORKER_COMMIT != candidate"; exit 1; }
WORKER_BIN="$WORKER_PKG/worker/.lake/build/bin/nbdsl_worker"
WORKER_SHA256=$(sha256sum "$WORKER_BIN" | cut -d' ' -f1)

# --- external semantic conformance profile against this checkout ---
# (its result carries the runtime provenance this job asserts on below)
# The checkout's venv owns jupyter_client AND the casdsl kernelspec the
# runner drives — the system python owns neither. This is the full matrix:
# Journey 2 atomicity, Journey 3 queries, Journey 4 repeated recovery, and
# Journey 5 transport-safe output.
"$CO/.venv/bin/python" "$KERNEL_REPO/conformance/runner.py" "$PROFILE" \
  --journey all --source-dir "$CO" \
  --output "$WORKDIR/conformance-result.json"

# --- the pair this candidate actually ran must agree, strictly ---
# Runtime already refuses a clean commit mismatch (see protocol.compare); this
# is the independent second gate. Both halves here come from one controlled
# checkout at one candidate SHA, so the bar is exactly `True` — a session that
# merely was not refused (unverifiable-dirty) does not qualify a release.
python3 - "$WORKDIR/conformance-result.json" "$CANDIDATE" "$WORKER_SHA256" <<'EOF'
import json, sys
res = json.load(open(sys.argv[1]))
candidate = sys.argv[2]
expected_hash = sys.argv[3]
prov = res.get("provenance", {})
if prov.get("status") != "present":
    sys.exit(f"qualification: no runtime provenance observed ({prov!r})")
records = prov.get("data") or []
if not records:
    sys.exit("qualification: provenance channel carried no record")
for p in records:
    if p.get("agreed") is not True:
        sys.exit(f"qualification: adapter/worker pair not strictly agreed: "
                 f"{p.get('agreed')!r}\n  adapter={p.get('adapter')}\n"
                 f"  worker={p.get('worker')}")
    for half in ("adapter", "worker"):
        got = (p.get(half) or {}).get("commit")
        if got != candidate:
            sys.exit(f"qualification: {half} ran at {got}, not the candidate "
                     f"{candidate}")
    got_hash = p.get("worker_binary_sha256")
    if got_hash != expected_hash:
        sys.exit("qualification: runtime worker hash does not match the "
                 f"qualified binary ({got_hash!r} != {expected_hash!r})")
print(f"provenance: adapter and worker both at {candidate}, strictly agreed")
EOF

# --- unchanged-worktree proof: exactly the declared overrides, nothing else ---
git -C "$CO" status --porcelain > "$WORKDIR/worktree-status.txt"
git -C "$CO" diff --binary > "$WORKDIR/actual-overrides.diff"
cmp "$WORKDIR/expected-overrides.diff" "$WORKDIR/actual-overrides.diff" || {
  echo "worktree content differs from the exact declared dependency overrides"
  exit 1
}
# LC_ALL=C so the comparison cannot depend on the runner's collation (a
# locale that folds punctuation orders lakefile.lean before
# lake-manifest.json; the C locale does the reverse).
DIRTY=$(awk '{print $NF}' "$WORKDIR/worktree-status.txt" | LC_ALL=C sort | tr '\n' ' ')
DECLARED="justfile lake-manifest.json lakefile.lean "
if [ "$DIRTY" != "$DECLARED" ]; then
  echo "worktree carries more than the declared overrides"
  echo "  declared: $DECLARED"
  echo "  actual:   $DIRTY"
  exit 1
fi
[ "$(git -C "$CO" rev-parse HEAD)" = "$BASELINE" ] || { echo "checkout moved off baseline"; exit 1; }

TOOLCHAIN=$(cat "$WORKER_PKG/worker/lean-toolchain" 2>/dev/null || cat "$CO/lean-toolchain")
E2E_LINE=$(grep -E "[0-9]+ passed" "$WORKDIR/consumer-gate.log" | tail -1 | sed 's/^ *//')

python3 - "$WORKDIR" <<EOF
import json, sys
json.dump({
  "schema": 1,
  "ai_review_ci_sha": "$AI_REVIEW_CI_SHA",
  "consumer_commit": "$BASELINE",
  "candidate_kernel_sha": "$CANDIDATE",
  "lean_toolchain": "$TOOLCHAIN".strip(),
  "lake_resolved_rev": "$RESOLVED",
  "adapter_pip_commit": "$PIP_COMMIT",
  "worker_checkout_commit": "$WORKER_COMMIT",
  "worker_binary_sha256": "$WORKER_SHA256",
  "consumer_gate": "$E2E_LINE",
  "conformance_result": "conformance-result.json",
  "worktree_overrides_only": True,
}, open(sys.argv[1] + "/qualification-evidence.json", "w"), indent=2)
EOF
echo "== QUALIFIED: evidence in $WORKDIR/qualification-evidence.json =="
