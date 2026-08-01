"""The adapter's build identity: one implementation, two callers.

`hatch_build.py` bakes this into the wheel at build time. `just build` calls
`scripts/sync_build_info.py`, which rewrites it in place so the adapter's half
is refreshed in step with the worker's — an editable install reads this file
from the source tree, so without that the two halves drift apart and the
runtime comparison refuses a pair that only looks mismatched.

Stdlib only, and it must never import the `nbdsl_kernel` package: this runs
inside hatchling's isolated build environment, where the package and its
dependencies do not exist yet.
"""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from email.parser import Parser
from pathlib import Path
from typing import Any

#: Written relative to the `nbdsl_kernel` project directory (the one holding
#: pyproject.toml). Gitignored — a tracked file cannot truthfully contain its
#: own commit.
BUILD_INFO = "nbdsl_kernel/_build_info.json"
IDENTITY_FIELDS = {
    "release",
    "commit",
    "dirty",
    "plugin_api",
    "wire",
    "toolchain",
    "mathlib",
}
COMMIT = re.compile(r"[0-9a-f]{40}")


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"nbdsl-kernel: `git {' '.join(args)}` failed in {root} "
            f"(exit {proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout.strip()


def _validate_identity(identity: dict[str, Any]) -> dict[str, Any]:
    if set(identity) != IDENTITY_FIELDS:
        raise RuntimeError(
            f"nbdsl-kernel: invalid build identity fields {sorted(identity)}")
    if not isinstance(identity["release"], str):
        raise RuntimeError("nbdsl-kernel: build release must be text")
    if not isinstance(identity["commit"], str) or not COMMIT.fullmatch(
            identity["commit"]):
        raise RuntimeError(
            "nbdsl-kernel: build commit must be a lowercase full SHA")
    if type(identity["dirty"]) is not bool:
        raise RuntimeError("nbdsl-kernel: build dirty flag must be boolean")
    for field in ("plugin_api", "wire"):
        if type(identity[field]) is not int:
            raise RuntimeError(
                f"nbdsl-kernel: build {field} must be an integer")
    for field in ("toolchain", "mathlib"):
        if not isinstance(identity[field], str):
            raise RuntimeError(
                f"nbdsl-kernel: build {field} must be text")
    return identity


def build_identity(project: Path) -> dict[str, Any]:
    """The identity of the adapter built from `project`, from the only two
    authoritative sources: the repository's `release.toml` and git.

    `project` is the `nbdsl_kernel` project directory; `release.toml` is its
    parent's — true for a source checkout and for
    `pip install git+…#subdirectory=nbdsl_kernel`, which clones the whole
    repository. A missing release.toml or git identity raises: an adapter
    that cannot say what it was built from must not exist.
    """
    release = tomllib.loads((project.parent / "release.toml").read_text())
    return _validate_identity({
        "release": release["release"]["version"],
        "commit": _git(project, "rev-parse", "HEAD"),
        # Tracked modifications only — `dirty` must mean "the SOURCE differs
        # from this commit", not "some tool wrote a file here". Installers do
        # exactly that: `uv pip install git+…` leaves its own untracked `.ok`
        # sentinel in the checkout, which made every uv-installed adapter
        # report dirty and so permanently disabled the strict clean-pair
        # commit comparison for the documented consumer install path
        # (observed, 2026-07-31). Same definition as `git describe --dirty`,
        # and the same one the worker's lakefile uses — the two flags feed one
        # comparison.
        #
        # Recorded, never a build failure: dev builds must run, and release
        # qualification is what rejects a dirty tree.
        "dirty": bool(_git(project, "status", "--porcelain",
                           "--untracked-files=no")),
        "plugin_api": release["compat"]["plugin_api"],
        "wire": release["compat"]["wire_protocol"],
        "toolchain": release["toolchain"]["lean"],
        "mathlib": release["toolchain"]["mathlib"],
    })


def sdist_identity(project: Path) -> dict[str, Any]:
    """Read the Git-derived identity carried by a generated sdist.

    ``PKG-INFO`` is the source-distribution marker. Its authenticated package
    metadata and the embedded identity must agree before the identity can be
    propagated into a wheel.
    """
    metadata = Parser().parsestr((project / "PKG-INFO").read_text())
    package = tomllib.loads((project / "pyproject.toml").read_text())["project"]
    if metadata["Name"] != package["name"]:
        raise RuntimeError("nbdsl-kernel: sdist package name is inconsistent")
    if metadata["Version"] != package["version"]:
        raise RuntimeError("nbdsl-kernel: sdist package version is inconsistent")
    identity: dict[str, Any] = json.loads(
        (project / BUILD_INFO).read_text())
    identity = _validate_identity(identity)
    if identity["release"] != metadata["Version"]:
        raise RuntimeError(
            "nbdsl-kernel: sdist identity release is inconsistent")
    return identity


def identity_for_build(project: Path) -> dict[str, Any]:
    """Choose one explicit provenance carrier for this source-tree kind."""
    git_checkout = subprocess.run(
        ["git", "-C", str(project), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
    )
    if git_checkout.returncode != 0 and (project / "PKG-INFO").is_file():
        return sdist_identity(project)
    return build_identity(project)


def write_build_info(project: Path) -> Path:
    path = project / BUILD_INFO
    path.write_text(json.dumps(identity_for_build(project), indent=2) + "\n")
    return path
