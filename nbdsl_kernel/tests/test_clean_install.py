"""Clean-environment installation and worker resolution, for both supported
dependency layouts.

Nothing here reuses the source checkout's `.venv`, an editable install, or a
preinstalled kernelspec: the adapter wheel is built, installed into a fresh
venv, and a kernelspec is installed from a minimal Lean project that owns its
worker through exactly one dependency edge.

The claim is about the binary the kernel actually EXECUTES, so it is read from
`/proc/<pid>/exe` of the live worker process — `find_worker_exe` is the code
under test, not evidence about it. The expected path is derived from how the
fixture was laid out, never from the adapter.

The two layouts are the ones a plugin can arrive through:

  path — the project requires «nbdsl-worker» from a local directory, which Lake
         builds in place, outside the project's own `.lake`;
  git  — the project requires a plugin package from git, and that plugin
         requires the worker from a git repository's `worker` subdirectory, so
         the exe lands one level below the flat `.lake/packages/*` layout.

Fixtures are generated rather than committed: every lakefile has to name an
absolute path or `file://` URL that only exists at test time.

Run: .venv/bin/pytest nbdsl_kernel/tests/test_clean_install.py
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import pytest
from jupyter_client.kernelspec import KernelSpecManager
from jupyter_client.manager import KernelManager

from test_e2e import run_cell, texts

REPO = Path(__file__).resolve().parents[2]
WORKER_SRC = REPO / "worker"
BUILD_TIMEOUT = 1800  # a cold worker build plus a git fetch, on a busy machine

# The prelude constant every layout's own prelude module defines: reading it
# back proves the session imported the prelude this project's dependency graph
# provides, not some other module that happens to be on LEAN_PATH.
PRELUDE_ANSWER = "def cleanAnswer : Nat := 41\n"


def _env() -> dict[str, str]:
    """The ambient environment minus everything that could smuggle the source
    checkout into a supposedly clean process."""
    drop = {"PYTHONPATH", "VIRTUAL_ENV", "JUPYTER_DATA_DIR", "JUPYTER_PATH",
            "NBDSL_PROJECT", "NBDSL_PRELUDE", "NBDSL_INIT"}
    return {k: v for k, v in os.environ.items() if k not in drop}


def _run(cmd: list[str], cwd: Path | None = None,
         env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(cmd, cwd=cwd, env=env or _env(), text=True,
                          capture_output=True, timeout=BUILD_TIMEOUT)
    if proc.returncode:
        raise RuntimeError(f"{cmd} failed ({proc.returncode}) in {cwd}\n"
                           f"{proc.stdout}\n{proc.stderr}")
    return proc.stdout


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# -- the clean adapter environment ----------------------------------------


@dataclass(frozen=True)
class CleanEnv:
    venv: Path
    python: Path
    wheel: Path


@pytest.fixture(scope="session")
def clean_env(tmp_path_factory: pytest.TempPathFactory) -> CleanEnv:
    """A fresh venv holding the built adapter wheel and its declared
    dependencies. The wheel is built by this venv's pip (in pip's own isolated
    build environment) and then installed as an artifact."""
    root = tmp_path_factory.mktemp("clean-adapter")
    venv, wheelhouse = root / "venv", root / "wheelhouse"
    _run([sys.executable, "-m", "venv", str(venv)])
    python = venv / "bin" / "python"
    _run([str(python), "-m", "pip", "wheel", "--no-deps",
          "-w", str(wheelhouse), str(REPO / "nbdsl_kernel")])
    wheels = list(wheelhouse.glob("nbdsl_kernel-*.whl"))
    assert len(wheels) == 1, wheels
    _run([str(python), "-m", "pip", "install", str(wheels[0])])
    return CleanEnv(venv=venv, python=python, wheel=wheels[0])


# -- the two dependency layouts -------------------------------------------


@dataclass(frozen=True)
class Layout:
    kind: str
    project: Path
    prelude: str
    #: Where this project's dependency graph puts the worker exe. Derived from
    #: the fixture's own construction, so it is an independent expectation.
    worker_exe: Path


def _write_project(proj: Path, lakefile: str) -> None:
    proj.mkdir(parents=True)
    (proj / "lean-toolchain").write_text((WORKER_SRC / "lean-toolchain").read_text())
    (proj / "lakefile.lean").write_text(lakefile)


def _local_path_layout(root: Path) -> Layout:
    """A clean project requiring the worker package from a local directory.

    The worker build embeds its git identity and hard-fails without one, and
    the adapter guard requires clean-tree identities to MATCH — so the local
    directory must carry this repository's real history, not a bare copy or a
    freshly initialized one. A file:// clone at HEAD is exactly that."""
    kernel_src = root / "kernel-src"
    _run(["git", "clone", "-q", f"file://{REPO}", str(kernel_src)])
    worker_pkg = kernel_src / "worker"
    proj = root / "project"
    _write_project(proj, "import Lake\nopen Lake DSL\n\n"
                         "package cleanpath\n\n"
                         f'require «nbdsl-worker» from "{worker_pkg}"\n\n'
                         "@[default_target]\nlean_lib CleanPrelude\n")
    (proj / "CleanPrelude.lean").write_text("import Worker.Output\n\n" + PRELUDE_ANSWER)
    _run(["lake", "build", "nbdsl_worker", "CleanPrelude"], cwd=proj)
    return Layout("path", proj, "CleanPrelude",
                  worker_pkg / ".lake/build/bin/nbdsl_worker")


def _git_commit(repo: Path, root: Path, message: str) -> str:
    """Commit without firing this workstation's global commit gate — a fixture
    repository has no justfile and owes it no proof."""
    hooks = root / "nohooks"
    hooks.mkdir(exist_ok=True)
    _run(["git", "init", "-q", "-b", "main", "."], cwd=repo)
    _run(["git", "add", "-A"], cwd=repo)
    _run(["git", "-c", f"core.hooksPath={hooks}", "-c", "user.email=fixture@invalid",
          "-c", "user.name=fixture", "commit", "-q", "-m", message], cwd=repo)
    return _run(["git", "rev-parse", "HEAD"], cwd=repo).strip()


def _nested_git_layout(root: Path) -> Layout:
    """A clean project requiring a plugin from git, where the plugin requires
    the worker from this repository's `worker` subdirectory — the shape that
    puts the exe one level below `.lake/packages/*`."""
    kernel_rev = _run(["git", "rev-parse", "HEAD"], cwd=REPO).strip()
    plugin = root / "plugin-src"
    (plugin / "DemoPlugin").mkdir(parents=True)
    (plugin / "lean-toolchain").write_text((WORKER_SRC / "lean-toolchain").read_text())
    (plugin / "lakefile.lean").write_text(
        "import Lake\nopen Lake DSL\n\n"
        "package «demo-plugin»\n\n"
        f'require «nbdsl-worker» from git "file://{REPO}" @ "{kernel_rev}" / "worker"\n\n'
        "@[default_target]\nlean_lib DemoPlugin\n")
    (plugin / "DemoPlugin.lean").write_text("import DemoPlugin.Notebook\n")
    (plugin / "DemoPlugin" / "Notebook.lean").write_text(
        "import Worker.Output\n\n" + PRELUDE_ANSWER)
    plugin_rev = _git_commit(plugin, root, "minimal nested plugin package")
    bare = root / "plugin.git"
    _run(["git", "clone", "-q", "--bare", str(plugin), str(bare)])

    proj = root / "project"
    _write_project(proj, "import Lake\nopen Lake DSL\n\n"
                         "package cleangit\n\n"
                         f'require «demo-plugin» from git "file://{bare}" @ "{plugin_rev}"\n')
    _run(["lake", "build", "nbdsl_worker", "DemoPlugin"], cwd=proj)
    return Layout("git", proj, "DemoPlugin.Notebook",
                  proj / ".lake/packages/nbdsl-worker/worker/.lake/build/bin/nbdsl_worker")


@pytest.fixture(scope="session", params=["path", "git"])
def layout(request: pytest.FixtureRequest,
           tmp_path_factory: pytest.TempPathFactory) -> Layout:
    kind: str = request.param
    root = tmp_path_factory.mktemp(f"layout-{kind}")
    built = (_local_path_layout if kind == "path" else _nested_git_layout)(root)
    assert built.worker_exe.exists(), \
        f"{kind} layout did not build its worker at {built.worker_exe}"
    return built


@pytest.fixture(scope="session")
def kernelspec(clean_env: CleanEnv, layout: Layout,
               tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    """Install a kernelspec for this layout into an empty Jupyter data
    directory. Returns (kernels dir, kernelspec name)."""
    data = tmp_path_factory.mktemp(f"jupyter-{layout.kind}")
    name = f"clean-{layout.kind}"
    _run([str(clean_env.python), "-m", "nbdsl_kernel.install",
          "--project", str(layout.project), "--name", name,
          "--prelude-module", layout.prelude],
         env={**_env(), "JUPYTER_DATA_DIR": str(data)})
    assert (data / "kernels" / name / "kernel.json").exists()
    return data / "kernels", name


# -- driving the installed kernelspec --------------------------------------


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
    """The nbdsl_worker process this kernel spawned, and the binary image it is
    running — read from the process, not from any path the adapter reports."""
    children: dict[int, list[int]] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            status = (entry / "status").read_text()
        except OSError:  # exited between listing and reading
            continue
        for line in status.splitlines():
            if line.startswith("PPid:"):
                children.setdefault(int(line.split()[1]), []).append(int(entry.name))
                break
    found: list[tuple[int, Path]] = []
    stack = [kernel_pid]
    while stack:
        for pid in children.get(stack.pop(), []):
            stack.append(pid)
            try:
                exe = Path(os.readlink(f"/proc/{pid}/exe"))
            except OSError:
                continue
            if exe.name == "nbdsl_worker":
                found.append((pid, exe))
    assert len(found) == 1, f"expected one live worker under pid {kernel_pid}: {found}"
    return found[0]


def test_adapter_runs_from_the_built_wheel(clean_env: CleanEnv) -> None:
    """Every other claim here rests on the environment being clean: the adapter
    the kernelspec will launch is the installed wheel, not the checkout."""
    located = Path(_run([str(clean_env.python), "-c",
                         "import nbdsl_kernel; print(nbdsl_kernel.__file__)"]).strip())
    assert located.is_relative_to(clean_env.venv), located
    assert not located.is_relative_to(REPO), located


def test_clean_install_executes_the_projects_own_worker(
        clean_env: CleanEnv, layout: Layout,
        kernelspec: tuple[Path, str]) -> None:
    kernels, name = kernelspec
    with _kernel(kernels, name) as (km, kc):
        # Reading the prelude constant proves the worker imported the prelude
        # module this layout supplies.
        reply, _ = run_cell(kc, "def x : Nat := cleanAnswer")
        assert reply["status"] == "ok", reply
        pid, exe = _live_worker(km.provisioner.process.pid)
        running = _sha256(Path(f"/proc/{pid}/exe"))
        reply, outputs = run_cell(kc, "#eval x + 1")
        assert reply["status"] == "ok", reply
        assert "42" in texts(outputs), texts(outputs)
    assert exe == layout.worker_exe.resolve(), exe
    assert running == _sha256(layout.worker_exe)
    # The checkout has its own built worker; resolution must not have found it.
    assert not exe.is_relative_to(REPO), exe


def test_missing_worker_fails_loudly(clean_env: CleanEnv, layout: Layout,
                                     kernelspec: tuple[Path, str]) -> None:
    """A project whose worker is gone (cleaned build tree, half-fetched
    dependency) must fail typed rather than reach for another binary."""
    kernels, name = kernelspec
    absent = layout.worker_exe.with_name("nbdsl_worker.absent")
    layout.worker_exe.rename(absent)
    try:
        with _kernel(kernels, name) as (_, kc):
            reply, _ = run_cell(kc, "def x : Nat := cleanAnswer")
    finally:
        absent.rename(layout.worker_exe)
    assert reply["status"] == "error", reply
    assert reply["ename"] == "WorkerDied", reply
