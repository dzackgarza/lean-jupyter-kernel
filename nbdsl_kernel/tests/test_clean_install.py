"""Clean-environment installation and worker resolution (nested Git/Lake).

Nothing here reuses the source checkout's `.venv`, an editable install, or a
preinstalled kernelspec: the adapter wheel is built, installed into a fresh
venv, and a kernelspec is installed from a minimal Lean project that owns its
worker through exactly one dependency edge.

The claim is about the binary the kernel actually EXECUTES, so it is read from
`/proc/<pid>/exe` of the live worker process — `find_worker_exe` is the code
under test, not evidence about it. The expected path is derived from how the
fixture was laid out, never from the adapter.

Layout: the project requires a plugin package from git, and that plugin
requires the worker from a git repository's `worker` subdirectory, so the exe
lands one level below the flat `.lake/packages/*` layout.

Fixtures are generated rather than committed: every lakefile has to name an
absolute path or `file://` URL that only exists at test time.

Run: .venv/bin/pytest nbdsl_kernel/tests/test_clean_install.py
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import pytest
from jupyter_client.kernelspec import KernelSpecManager
from jupyter_client.manager import KernelManager

from jupyter_helpers import clean_jupyter_env, find_worker_under
from test_e2e import run_cell, texts

REPO = Path(__file__).resolve().parents[2]
BUILD_TIMEOUT = 1800  # a cold worker build plus a git fetch, on a busy machine

WORKER_SRC = REPO / "worker"
NBDSL_CACHE = REPO / "dsls" / "nbdsl" / ".lake" / "packages"
NBDSL_MATHLIB = NBDSL_CACHE / "mathlib"


def _env() -> dict[str, str]:
    return clean_jupyter_env()


def _run(cmd: list[str], cwd: Path | None = None,
         env: dict[str, str] | None = None,
         include_stderr: bool = False) -> str:
    proc = subprocess.run(cmd, cwd=cwd,
                          env=_env() if env is None else env, text=True,
                          capture_output=True, timeout=BUILD_TIMEOUT)
    if proc.returncode:
        raise RuntimeError(f"{cmd} failed ({proc.returncode}) in {cwd}\n"
                           f"{proc.stdout}\n{proc.stderr}")
    return proc.stdout + proc.stderr if include_stderr else proc.stdout


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class CleanEnv:
    venv: Path
    python: Path
    adapter_wheel: Path
    lab_wheel: Path


@pytest.fixture(scope="session")
def clean_env(tmp_path_factory: pytest.TempPathFactory) -> CleanEnv:
    """A fresh venv holding the built adapter wheel and its declared deps."""
    root = tmp_path_factory.mktemp("clean-adapter")
    venv, wheelhouse = root / "venv", root / "wheelhouse"
    _run([sys.executable, "-m", "venv", str(venv)])
    python = venv / "bin" / "python"
    _run([str(python), "-m", "pip", "wheel", "--no-deps",
          "-w", str(wheelhouse), str(REPO / "nbdsl_kernel")])
    _run([sys.executable, "-m", "build", "--wheel",
          "--outdir", str(wheelhouse), str(REPO / "jupyterlab_nbdsl")])
    adapter_wheels = list(wheelhouse.glob("nbdsl_kernel-*.whl"))
    lab_wheels = list(wheelhouse.glob("jupyterlab_nbdsl-*.whl"))
    assert len(adapter_wheels) == 1, adapter_wheels
    assert len(lab_wheels) == 1, lab_wheels
    _run([str(python), "-m", "pip", "install",
          str(adapter_wheels[0]), str(lab_wheels[0])])
    return CleanEnv(venv=venv, python=python,
                    adapter_wheel=adapter_wheels[0],
                    lab_wheel=lab_wheels[0])


@dataclass(frozen=True)
class Layout:
    kind: str
    project: Path
    prelude: str
    #: Where this project's dependency graph puts the worker exe.
    worker_exe: Path


def _write_project(proj: Path, lakefile: str) -> None:
    proj.mkdir(parents=True)
    (proj / "lean-toolchain").write_text((WORKER_SRC / "lean-toolchain").read_text())
    (proj / "lakefile.lean").write_text(lakefile)


def _configure_fixture_plugin(package: Path, worker_require: str) -> None:
    """Use the cached Mathlib package while rewriting one worker edge."""
    lakefile = package / "lakefile.lean"
    source = lakefile.read_text()
    if NBDSL_MATHLIB.is_dir():
        mathlib = re.compile(
            r'require mathlib from git\n\s+'
            r'"https://github\.com/leanprover-community/mathlib4\.git" '
            r'@ "[^"]+"')
        source, count = mathlib.subn(
            f'require mathlib from "{NBDSL_MATHLIB}"', source)
        assert count == 1, lakefile
    source, count = re.subn(
        r'require «nbdsl-worker» from .*?(?=\n\n)',
        worker_require, source, count=1, flags=re.DOTALL)
    assert count == 1, lakefile
    lakefile.write_text(source)
    manifest = package / "lake-manifest.json"
    if manifest.exists():
        manifest.unlink()


def _git_commit(repo: Path, root: Path, message: str) -> str:
    """Commit without firing this workstation's global commit gate."""
    hooks = root / "nohooks"
    hooks.mkdir(exist_ok=True)
    _run(["git", "init", "-q", "-b", "main", "."], cwd=repo)
    _run(["git", "add", "-A"], cwd=repo)
    _run(["git", "-c", f"core.hooksPath={hooks}", "-c", "user.email=fixture@invalid",
          "-c", "user.name=fixture", "commit", "-q", "-m", message], cwd=repo)
    return _run(["git", "rev-parse", "HEAD"], cwd=repo).strip()


def _nested_git_layout(root: Path) -> Layout:
    """Clean project requiring NbDsl from git; NbDsl requires worker from git."""
    kernel_rev = _run(["git", "rev-parse", "HEAD"], cwd=REPO).strip()
    plugin = root / "nbdsl-plugin-src"
    _run(["git", "clone", "-q", f"file://{REPO}", str(plugin)])
    git_require = (
        f'require «nbdsl-worker» from git "file://{REPO}" '
        f'@ "{kernel_rev}" / "worker"')
    _configure_fixture_plugin(plugin / "dsls" / "nbdsl", git_require)
    plugin_rev = _git_commit(plugin, root, "minimal nested plugin package")
    bare = root / "nbdsl-plugin.git"
    _run(["git", "clone", "-q", "--bare", str(plugin), str(bare)])

    proj = root / "project"
    _write_project(proj, "import Lake\nopen Lake DSL\n\n"
                         "package cleangit\n\n"
                         f'require nbdsl from git "file://{bare}" '
                         f'@ "{plugin_rev}" / "dsls/nbdsl"\n')
    _run(["lake", "update"], cwd=proj)
    _run(["lake", "build", "nbdsl_worker", "NbDsl"], cwd=proj)
    manifest = json.loads((proj / "lake-manifest.json").read_text())
    worker = next(
        package for package in manifest["packages"]
        if package["name"].strip("«»") == "nbdsl-worker")
    assert worker["type"] == "git", worker
    assert worker["url"] == f"file://{REPO}", worker
    assert worker["rev"] == kernel_rev, worker
    worker_dir = (proj / ".lake" / "packages" / "nbdsl-worker"
                  / worker["subDir"])
    return Layout(
        "git", proj, "NbDsl.Notebook",
        worker_dir / ".lake/build/bin/nbdsl_worker")


@pytest.fixture(scope="session")
def layout(tmp_path_factory: pytest.TempPathFactory) -> Layout:
    root = tmp_path_factory.mktemp("layout-git")
    built = _nested_git_layout(root)
    assert built.worker_exe.exists(), \
        f"git layout did not build its worker at {built.worker_exe}"
    return built


@pytest.fixture(scope="session")
def kernelspec(clean_env: CleanEnv, layout: Layout,
               tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    """Install a kernelspec for this layout into an empty Jupyter data dir."""
    data = tmp_path_factory.mktemp(f"jupyter-{layout.kind}")
    name = f"clean-{layout.kind}"
    _run([str(clean_env.python), "-m", "nbdsl_kernel.install",
          "--project", str(layout.project), "--name", name,
          "--prelude-module", layout.prelude],
         env={**_env(), "JUPYTER_DATA_DIR": str(data)})
    assert (data / "kernels" / name / "kernel.json").exists()
    return data / "kernels", name


@contextmanager
def _kernel(kernels: Path, name: str) -> Iterator[tuple[Any, Any]]:
    ksm = KernelSpecManager(kernel_dirs=[str(kernels)])
    km = KernelManager(kernel_name=name, kernel_spec_manager=ksm)
    km.start_kernel(env=_env())
    kc = km.client()
    kc.start_channels()
    try:
        kc.wait_for_ready(timeout=120)
        yield km, kc
    finally:
        kc.stop_channels()
        km.shutdown_kernel(now=True)


def _live_worker(kernel_pid: int) -> tuple[int, Path]:
    """Live nbdsl_worker under the kernel, plus the binary image it is running."""
    pid, _ = find_worker_under(kernel_pid)
    return pid, Path(os.readlink(f"/proc/{pid}/exe"))


def test_adapter_runs_from_the_built_wheel(clean_env: CleanEnv) -> None:
    """Every other claim rests on the adapter being the installed wheel."""
    located = Path(_run([str(clean_env.python), "-c",
                         "import nbdsl_kernel; print(nbdsl_kernel.__file__)"]).strip())
    assert located.is_relative_to(clean_env.venv), located
    assert not located.is_relative_to(REPO), located


def test_labextension_runs_from_the_built_wheel(
        clean_env: CleanEnv,
        tmp_path_factory: pytest.TempPathFactory) -> None:
    """Production labextension installs from the wheel, not a checkout link."""
    data = tmp_path_factory.mktemp("jupyter-lab")
    output = _run(
        [str(clean_env.python), "-m", "jupyter", "labextension", "list"],
        env={**_env(), "JUPYTER_DATA_DIR": str(data)},
        include_stderr=True)
    assert "jupyterlab_nbdsl" in output, output
    assert "enabled" in output and "OK" in output, output

    extension = (clean_env.venv / "share" / "jupyter" / "labextensions"
                 / "jupyterlab_nbdsl")
    assert extension.is_dir() and not extension.is_symlink(), extension
    assert not extension.resolve().is_relative_to(REPO), extension
    assert (extension / "package.json").exists(), extension


def test_clean_install_executes_the_projects_own_worker(
        clean_env: CleanEnv, layout: Layout,
        kernelspec: tuple[Path, str]) -> None:
    kernels, name = kernelspec
    spec = json.loads((kernels / name / "kernel.json").read_text())
    assert spec["argv"][0] == str(clean_env.python)
    assert spec["env"]["NBDSL_PRELUDE"] == "NbDsl.Notebook"
    assert spec["metadata"]["nbdsl"]["project_root"] == str(layout.project)
    with _kernel(kernels, name) as (km, kc):
        reply, _ = run_cell(kc, "def x : Nat := 41")
        assert reply["status"] == "ok", reply
        pid, exe = _live_worker(km.provisioner.process.pid)
        running = _sha256(Path(f"/proc/{pid}/exe"))
        reply, outputs = run_cell(kc, "#eval x + 1")
        assert reply["status"] == "ok", reply
        assert "42" in texts(outputs), texts(outputs)
        reply, _ = run_cell(
            kc, "open NbDsl NbDsl.Std\n"
                "prefer groupsToSets\n"
                "let G := GrpCat.of PUnit ∈ Groups")
        assert reply["status"] == "ok", reply
        reply, outputs = run_cell(kc, "#via G ∈ Sets")
        assert reply["status"] == "ok", reply
        bundles = [
            m["content"]["data"] for m in outputs
            if m["msg_type"] in ("execute_result", "display_data")]
        assert any("application/vnd.nbdsl.path+json" in bundle
                   for bundle in bundles), bundles
    assert exe == layout.worker_exe.resolve(), exe
    assert running == _sha256(layout.worker_exe)
    assert not exe.is_relative_to(REPO), exe


def test_missing_worker_fails_loudly(clean_env: CleanEnv, layout: Layout,
                                     kernelspec: tuple[Path, str]) -> None:
    """A project whose worker is gone must fail typed, not reach for another."""
    kernels, name = kernelspec
    absent = layout.worker_exe.with_name("nbdsl_worker.absent")
    layout.worker_exe.rename(absent)
    try:
        with _kernel(kernels, name) as (_, kc):
            reply, _ = run_cell(kc, "def x : Nat := 41")
    finally:
        absent.rename(layout.worker_exe)
    assert reply["status"] == "error", reply
    assert reply["ename"] == "WorkerDied", reply
