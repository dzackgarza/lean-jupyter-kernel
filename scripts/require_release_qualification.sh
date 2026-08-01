#!/usr/bin/env bash
# Admit a release only when GitHub reports the governed CI contexts green on
# the exact tag-target commit.

set -euo pipefail

repository="${1:?usage: require_release_qualification.sh OWNER/REPO COMMIT_SHA}"
commit_sha="${2:?usage: require_release_qualification.sh OWNER/REPO COMMIT_SHA}"

check_runs="$(
  gh api --method GET \
    -H 'Accept: application/vnd.github+json' \
    -H 'X-GitHub-Api-Version: 2022-11-28' \
    "repos/${repository}/commits/${commit_sha}/check-runs" \
    -F filter=latest \
    -F per_page=100 \
    --paginate \
    --slurp
)"

unsatisfied="$(
  jq -r --arg commit_sha "${commit_sha}" '
    [
      "worker (mathlib-free gate)",
      "NbDsl + kernel round-trip + e2e",
      "jupyterlab extension",
      "compatibility + external consumer"
    ] as $required
    | [.[].check_runs[]] as $runs
    | $required[] as $context
    | ($runs | map(select(.name == $context)) | sort_by(.id) | last) as $run
    | if $run == null then
        "\($context): missing"
      elif $run.head_sha != $commit_sha then
        "\($context): head_sha=\($run.head_sha | tojson)"
      elif $run.status != "completed" or $run.conclusion != "success" then
        "\($context): status=\($run.status | tojson) conclusion=\($run.conclusion | tojson)"
      else
        empty
      end
  ' <<<"${check_runs}"
)"

if [[ -n "${unsatisfied}" ]]; then
  printf 'release qualification failed for commit %s:\n%s\n' \
    "${commit_sha}" "${unsatisfied}" >&2
  exit 1
fi

printf 'release qualification satisfied for commit %s: all four governed contexts succeeded\n' \
  "${commit_sha}"
