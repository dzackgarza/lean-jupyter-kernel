#!/usr/bin/env python3
"""Release provenance — bind the qualified commit to its built artifacts.

  generate --worker <bin> [--dist <file> ...] [--out release-provenance.json]
      Emit the provenance object: release.toml manifest hash, exact clean
      git commit, derived tag, governed package versions, worker binary
      hash, and SHA-256 of every named distribution file. A dirty tree or
      missing git identity is a hard failure — provenance is a release
      artifact, never a development convenience.

  verify --provenance <json> --worker <bin> [--dist <file> ...]
      Recompute every hash and identity and fail on any disagreement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_identity(allowed_untracked: list[Path]) -> str:
    commit = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "HEAD"],
        capture_output=True, text=True)
    if commit.returncode != 0:
        sys.exit("release provenance: missing git identity")
    tracked = subprocess.run(
        [
            "git", "-C", str(REPO), "status", "--porcelain",
            "--untracked-files=no",
        ],
        capture_output=True, text=True, check=True)
    if tracked.stdout.strip():
        sys.exit("release provenance: dirty tree — a release identity must "
                 "name an exact clean commit")
    untracked = subprocess.run(
        [
            "git", "-C", str(REPO), "ls-files", "--others",
            "--exclude-standard", "-z",
        ],
        capture_output=True, check=True)
    untracked_paths = {
        path.decode(errors="surrogateescape")
        for path in untracked.stdout.split(b"\0")
        if path
    }
    repository = REPO.resolve()
    allowed_untracked_paths: set[str] = set()
    for artifact in allowed_untracked:
        selected = artifact.resolve()
        if selected.is_relative_to(repository):
            allowed_untracked_paths.add(
                selected.relative_to(repository).as_posix())
    if not untracked_paths.issubset(allowed_untracked_paths):
        sys.exit("release provenance: dirty tree — a release identity must "
                 "name an exact clean commit")
    return commit.stdout.strip()


def build(
    worker: Path,
    dists: list[Path],
    allowed_untracked: list[Path],
) -> dict[str, object]:
    release = tomllib.loads((REPO / "release.toml").read_text())
    version = release["release"]["version"]
    missing = [str(p) for p in [worker, *dists] if not p.is_file()]
    if missing:
        sys.exit(f"release provenance: missing artifacts: {missing}")
    names = [path.name for path in dists]
    if len(names) != len(set(names)):
        sys.exit("release provenance: distribution basenames must be unique")
    return {
        "schema": 1,
        "commit": git_identity(allowed_untracked),
        "tag": f"v{version}",
        "release_manifest_sha256": sha256(REPO / "release.toml"),
        "release": {
            "version": version,
            "lean_toolchain": release["toolchain"]["lean"],
            "mathlib": release["toolchain"]["mathlib"],
            "mathlib_commit": release["toolchain"]["mathlib_commit"],
            "plugin_api": release["compat"]["plugin_api"],
            "wire_protocol": release["compat"]["wire_protocol"],
        },
        "worker_binary": {"path": str(worker), "sha256": sha256(worker)},
        "distributions": {p.name: sha256(p) for p in dists},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    ap.add_argument("mode", choices=["generate", "verify"])
    ap.add_argument("--worker", type=Path, required=True)
    ap.add_argument("--dist", type=Path, action="append", default=[])
    ap.add_argument("--out", type=Path,
                    default=REPO / "release-provenance.json")
    ap.add_argument("--provenance", type=Path)
    args = ap.parse_args()

    if args.mode == "generate":
        current = build(args.worker, args.dist,
                        [args.worker, *args.dist, args.out])
        args.out.write_text(json.dumps(current, indent=2) + "\n")
        print(f"wrote {args.out} for commit {current['commit']}")
        return

    if not args.provenance:
        sys.exit("verify requires --provenance")
    current = build(args.worker, args.dist,
                    [args.worker, *args.dist, args.provenance])
    recorded = json.loads(args.provenance.read_text())
    # The recorded worker path may differ across environments; identity is
    # the hash, not the location.
    recorded_cmp = {**recorded, "worker_binary": recorded["worker_binary"]["sha256"]}
    current_cmp = {**current, "worker_binary": current["worker_binary"]["sha256"]}
    if recorded_cmp != current_cmp:
        for key in current_cmp:
            if recorded_cmp.get(key) != current_cmp[key]:
                print(f"disagreement on {key}:\n  recorded: "
                      f"{recorded_cmp.get(key)}\n  current:  {current_cmp[key]}")
        sys.exit(1)
    print(f"provenance verified for commit {current['commit']}")


if __name__ == "__main__":
    main()
