"""Clean adapter-wheel install: kernelspec + meaningful NbDsl notebook cell.

Worker-path resolution belongs to ``test_worker_resolve.py``. Nested Git/Lake
consumer layout belongs to real ``lean-cas-dsl`` qualification. JupyterLab
wheel activation belongs to frontend CI.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from jupyter_client.kernelspec import KernelSpecManager
from jupyter_client.manager import KernelManager
from jupyter_helpers import clean_jupyter_env, find_worker_under
from test_e2e import run_cell, texts

REPO = Path(__file__).resolve().parents[2]
PROJECT = REPO / "dsls" / "nbdsl"
WORKER_EXE = REPO / "worker" / ".lake" / "build" / "bin" / "nbdsl_worker"
BUILD_TIMEOUT = 600


def _env() -> dict[str, str]:
    return clean_jupyter_env()


def _run(
    cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None
) -> str:
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        env=_env() if env is None else env,
        text=True,
        capture_output=True,
        timeout=BUILD_TIMEOUT,
    )
    if proc.returncode:
        raise RuntimeError(
            f"{cmd} failed ({proc.returncode}) in {cwd}\n{proc.stdout}\n{proc.stderr}"
        )
    return proc.stdout


@dataclass(frozen=True)
class CleanEnv:
    venv: Path
    python: Path
    adapter_wheel: Path


@pytest.fixture(scope="session")
def clean_env(tmp_path_factory: pytest.TempPathFactory) -> CleanEnv:
    root = tmp_path_factory.mktemp("clean-adapter")
    venv, wheelhouse = root / "venv", root / "wheelhouse"
    _run([sys.executable, "-m", "venv", str(venv)])
    python = venv / "bin" / "python"
    _run(
        [
            str(python),
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "-w",
            str(wheelhouse),
            str(REPO / "nbdsl_kernel"),
        ]
    )
    adapter_wheels = list(wheelhouse.glob("nbdsl_kernel-*.whl"))
    assert len(adapter_wheels) == 1, adapter_wheels
    _run([str(python), "-m", "pip", "install", str(adapter_wheels[0])])
    return CleanEnv(venv=venv, python=python, adapter_wheel=adapter_wheels[0])


@pytest.fixture(scope="session")
def kernelspec(
    clean_env: CleanEnv, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, str]:
    assert WORKER_EXE.exists(), f"build worker first: {WORKER_EXE}"
    data = tmp_path_factory.mktemp("jupyter-clean")
    name = "clean-nbdsl"
    _run(
        [
            str(clean_env.python),
            "-m",
            "nbdsl_kernel.install",
            "--project",
            str(PROJECT),
            "--name",
            name,
            "--prelude-module",
            "NbDsl.Notebook",
        ],
        env={**_env(), "JUPYTER_DATA_DIR": str(data)},
    )
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


def test_adapter_runs_from_the_built_wheel(clean_env: CleanEnv) -> None:
    located = Path(
        _run(
            [
                str(clean_env.python),
                "-c",
                "import nbdsl_kernel; print(nbdsl_kernel.__file__)",
            ]
        ).strip()
    )
    assert located.is_relative_to(clean_env.venv), located
    assert not located.is_relative_to(REPO), located


def test_clean_install_runs_dsl_notebook(
    clean_env: CleanEnv, kernelspec: tuple[Path, str]
) -> None:
    kernels, name = kernelspec
    spec = json.loads((kernels / name / "kernel.json").read_text())
    assert spec["argv"][0] == str(clean_env.python)
    assert spec["env"]["NBDSL_PRELUDE"] == "NbDsl.Notebook"
    assert spec["env"]["NBDSL_LANGUAGE_NAME"] == "lean4"
    assert spec["env"]["NBDSL_MIMETYPE"] == "text/x-lean4"
    assert spec["env"]["NBDSL_LANGUAGE_EXT"] == ".lean"
    assert spec["language"] == "lean4"
    assert spec["metadata"]["nbdsl"]["project_root"] == str(PROJECT)
    with _kernel(kernels, name) as (km, kc):
        reply, _ = run_cell(kc, "def x : Nat := 41")
        assert reply["status"] == "ok", reply
        pid, _ = find_worker_under(km.provisioner.process.pid)
        exe = Path(os.readlink(f"/proc/{pid}/exe"))
        reply, outputs = run_cell(kc, "#eval x + 1")
        assert reply["status"] == "ok", reply
        assert "42" in texts(outputs), texts(outputs)
        reply, _ = run_cell(
            kc,
            "open NbDsl NbDsl.Std\n"
            "prefer groupsToSets\n"
            "let G := GrpCat.of PUnit ∈ Groups",
        )
        assert reply["status"] == "ok", reply
        reply, outputs = run_cell(kc, "#via G ∈ Sets")
        assert reply["status"] == "ok", reply
        bundles = [
            m["content"]["data"]
            for m in outputs
            if m["msg_type"] in ("execute_result", "display_data")
        ]
        assert any("application/vnd.nbdsl.path+json" in bundle for bundle in bundles), (
            bundles
        )
    assert exe == WORKER_EXE.resolve(), exe
    assert not exe.is_relative_to(REPO / "nbdsl_kernel"), exe


def test_missing_worker_fails_loudly(
    clean_env: CleanEnv, kernelspec: tuple[Path, str]
) -> None:
    kernels, name = kernelspec
    absent = WORKER_EXE.with_name("nbdsl_worker.absent")
    WORKER_EXE.rename(absent)
    try:
        with _kernel(kernels, name) as (_, kc):
            reply, _ = run_cell(kc, "def x : Nat := 41")
    finally:
        absent.rename(WORKER_EXE)
    assert reply["status"] == "error", reply
    assert reply["ename"] == "WorkerDied", reply
