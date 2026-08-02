from __future__ import annotations

import shutil
import sys
import subprocess
import time
from pathlib import Path

import pytest

import nbdsl_kernel.resource_limits as resource_limits
from nbdsl_kernel.resource_limits import ResourceLimits, systemd_command


def test_systemd_command_has_hard_memory_cpu_and_runtime_bounds() -> None:
    limits = ResourceLimits(
        memory_high="3584M",
        memory_max="4G",
        memory_swap_max="0",
        cpu_quota="400%",
        tasks_max=128,
        runtime_max="1800s",
    )

    assert systemd_command([sys.executable, "-c", "pass"], limits) == [
        "systemd-run",
        "--user",
        "--scope",
        "--quiet",
        "-p",
        "MemoryHigh=3584M",
        "-p",
        "MemoryMax=4G",
        "-p",
        "MemorySwapMax=0",
        "-p",
        "OOMPolicy=kill",
        "-p",
        "KillMode=control-group",
        "-p",
        "CPUQuota=400%",
        "-p",
        "TasksMax=128",
        "-p",
        "RuntimeMaxSec=1800s",
        "--",
        sys.executable,
        "-c",
        "pass",
    ]


def test_default_limits_are_finite_and_disable_swap() -> None:
    limits = ResourceLimits()

    assert limits.memory_high != "infinity"
    assert limits.memory_max != "infinity"
    assert limits.memory_swap_max == "0"
    assert limits.cpu_quota == "400%"
    assert limits.tasks_max > 0
    assert limits.runtime_max != "infinity"


def test_launcher_places_child_in_a_finite_no_swap_scope() -> None:
    launcher = Path(__file__).parents[1] / "scripts/resource_limited.py"
    child = (
        "import os\n"
        "from pathlib import Path\n"
        "relative = next(line.split(':', 2)[2] for line in "
        "Path('/proc/self/cgroup').read_text().splitlines() "
        "if line.startswith('0::'))\n"
        "root = Path('/sys/fs/cgroup') / relative.lstrip('/')\n"
        "assert (root / 'memory.max').read_text().strip() != 'max'\n"
        "assert (root / 'memory.swap.max').read_text().strip() == '0'\n"
        "assert not (root / 'cpu.max').read_text().startswith('max ')\n"
        "assert os.environ.get('LEAN_NUM_THREADS') == '1'\n"
        "print('finite-resource-scope')\n"
    )
    completed = subprocess.run(
        [sys.executable, str(launcher), "--", sys.executable, "-c", child],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "finite-resource-scope" in completed.stdout


def test_interrupted_launcher_stops_its_systemd_scope() -> None:
    if (shutil.which("systemd-run") is None
            or shutil.which("systemctl") is None
            or resource_limits.active_resource_scope()
            or not resource_limits._systemd_scope_usable(
                resource_limits.TEST_LIMITS)):
        pytest.skip("an independent user systemd scope is unavailable")

    launcher = Path(__file__).parents[1] / "scripts/resource_limited.py"
    process = subprocess.Popen(
        [
            sys.executable,
            str(launcher),
            "--",
            sys.executable,
            "-c",
            "import time; time.sleep(60)",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    scope_name: str | None = None
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            listing = subprocess.run(
                [
                    "systemctl",
                    "--user",
                    "list-units",
                    "--type=scope",
                    "--state=active",
                    "--no-pager",
                    "--plain",
                ],
                capture_output=True,
                text=True,
                check=False,
            ).stdout
            match = next(
                (line for line in listing.splitlines()
                 if f"nbdsl-resource-{process.pid}-" in line),
                None,
            )
            if match is not None:
                scope_name = match.split()[0]
                break
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                raise AssertionError(
                    f"resource launcher exited before scope creation: "
                    f"{process.returncode}: {stdout}{stderr}")
            time.sleep(0.05)
        assert scope_name is not None

        process.terminate()
        assert process.wait(timeout=10) != 0

        listing = subprocess.run(
            [
                "systemctl",
                "--user",
                "list-units",
                "--type=scope",
                "--state=active",
                "--no-pager",
                "--plain",
            ],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        assert scope_name not in listing
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        if scope_name is not None:
            subprocess.run(
                ["systemctl", "--user", "stop", scope_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
