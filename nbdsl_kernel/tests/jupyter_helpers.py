"""Shared Jupyter install / worker-discovery helpers for adapter tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from jupyter_client.kernelspec import KernelSpecManager
from jupyter_client.manager import KernelManager

REPO = Path(__file__).resolve().parents[2]

_SCRUB = {
    "PYTHONPATH",
    "VIRTUAL_ENV",
    "JUPYTER_DATA_DIR",
    "JUPYTER_PATH",
    "NBDSL_INIT",
    "NBDSL_PROJECT",
    "NBDSL_PRELUDE",
}


def clean_jupyter_env(**overrides: str) -> dict[str, str]:
    """Ambient env minus keys that smuggle a source checkout into a clean run."""
    env = {k: v for k, v in os.environ.items() if k not in _SCRUB}
    env.update(overrides)
    return env


def find_worker_under(kernel_pid: int) -> tuple[int, int]:
    """Return ``(worker_pid, parent_pid)`` for the live ``nbdsl_worker``."""
    tree: dict[int, list[int]] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            status = (entry / "status").read_text()
        except OSError:
            continue
        for line in status.splitlines():
            if line.startswith("PPid:"):
                tree.setdefault(int(line.split()[1]), []).append(int(entry.name))
                break
    stack = [kernel_pid]
    while stack:
        parent = stack.pop()
        for pid in tree.get(parent, []):
            stack.append(pid)
            try:
                if Path(os.readlink(f"/proc/{pid}/exe")).name == "nbdsl_worker":
                    return pid, parent
            except OSError:
                continue
    raise AssertionError(f"no live nbdsl_worker under {kernel_pid}")


def start_init_kernel(
    tmp_path: Path,
    name: str,
    *,
    project: Path | None = None,
    prelude: str = "Init",
    init_cell: str = "",
    python: str | None = None,
) -> tuple[KernelManager, Any]:
    """Install a kernelspec and return ``(KernelManager, client)``."""
    data = tmp_path / "jupyter"
    env = clean_jupyter_env()
    command = [
        python or sys.executable,
        "-m",
        "nbdsl_kernel.install",
        "--project",
        str(project or REPO / "worker"),
        "--name",
        name,
        "--prelude-module",
        prelude,
    ]
    if init_cell:
        command.extend(["--init-cell", init_cell])
    subprocess.run(
        command,
        env={**env, "JUPYTER_DATA_DIR": str(data)},
        check=True,
        capture_output=True,
    )
    manager = KernelManager(
        kernel_name=name,
        kernel_spec_manager=KernelSpecManager(
            kernel_dirs=[str(data / "kernels")]
        ),
    )
    manager.start_kernel(env=env)
    client: Any = manager.client()
    client.start_channels()
    client.wait_for_ready(timeout=120)
    return manager, client


def await_execute(
        kc: Any, msg_id: str, timeout: float = 120
) -> tuple[dict[str, Any], list[Any]]:
    """Drain iopub until idle, then return the matching shell reply."""
    outputs: list[Any] = []
    while True:
        msg = kc.get_iopub_msg(timeout=timeout)
        if msg["parent_header"].get("msg_id") != msg_id:
            continue
        if (msg["msg_type"] == "status"
                and msg["content"]["execution_state"] == "idle"):
            break
        outputs.append(msg)
    while True:
        reply = kc.get_shell_msg(timeout=timeout)
        if reply["parent_header"].get("msg_id") == msg_id:
            return reply["content"], outputs
