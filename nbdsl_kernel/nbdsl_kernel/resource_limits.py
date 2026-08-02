"""Hard resource boundaries for worker-heavy repository commands.

The Lean worker is a process tree: the test runner starts Jupyter, the kernel
starts Lake, and Lake starts the worker. A shell lock and a thread limit do not
bound that tree. Prefer a transient user systemd scope; on systems without a
user manager, use a delegated cgroup v2 child and fail closed if neither is
available.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


class ResourceLimitError(RuntimeError):
    """The requested hard resource boundary cannot be established."""


@dataclass(frozen=True)
class ResourceLimits:
    """Finite defaults chosen to contain one worker-heavy repository gate."""

    memory_high: str = "5G"
    memory_max: str = "6G"
    memory_swap_max: str = "0"
    cpu_quota: str = "400%"
    tasks_max: int = 128
    runtime_max: str = "1800s"

    def __post_init__(self) -> None:
        if self.memory_high in {"max", "infinity"}:
            raise ValueError("memory_high must be finite")
        if self.memory_max in {"max", "infinity"}:
            raise ValueError("memory_max must be finite")
        if self.memory_swap_max != "0":
            raise ValueError("memory_swap_max must disable swap")
        if self.cpu_quota in {"max", "infinity"}:
            raise ValueError("cpu_quota must be finite")
        if self.tasks_max <= 0:
            raise ValueError("tasks_max must be positive")
        if self.runtime_max in {"max", "infinity"}:
            raise ValueError("runtime_max must be finite")


TEST_LIMITS = ResourceLimits()
QUALIFICATION_LIMITS = ResourceLimits(runtime_max="5400s")


def systemd_command(command: Sequence[str],
                    limits: ResourceLimits = TEST_LIMITS,
                    *, unit: str | None = None) -> list[str]:
    """Return a transient user scope command with hard finite limits."""
    if not command:
        raise ValueError("resource-limited command cannot be empty")
    properties = [
        ("MemoryHigh", limits.memory_high),
        ("MemoryMax", limits.memory_max),
        ("MemorySwapMax", limits.memory_swap_max),
        ("OOMPolicy", "kill"),
        ("KillMode", "control-group"),
        ("CPUQuota", limits.cpu_quota),
        ("TasksMax", str(limits.tasks_max)),
        ("RuntimeMaxSec", limits.runtime_max),
    ]
    unit_args = ["--unit", unit] if unit is not None else []
    return [
        "systemd-run",
        "--user",
        "--scope",
        "--quiet",
        *unit_args,
        *sum((["-p", f"{name}={value}"]
              for name, value in properties), []),
        "--",
        *command,
    ]


def _self_cgroup() -> Path:
    try:
        lines = Path("/proc/self/cgroup").read_text().splitlines()
        relative = next(
            line.split(":", 2)[2]
            for line in lines
            if line.startswith("0::"))
    except (OSError, StopIteration, IndexError) as exc:
        raise ResourceLimitError(
            "cannot determine the current cgroup v2 path") from exc
    return Path("/sys/fs/cgroup") / relative.lstrip("/")


def _read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError as exc:
        raise ResourceLimitError(f"cannot read resource control {path}") from exc


def active_resource_scope() -> bool:
    """Whether this process is already inside a finite no-swap cgroup."""
    try:
        cgroup = _self_cgroup()
        memory_max = _read(cgroup / "memory.max")
        memory_swap_max = _read(cgroup / "memory.swap.max")
        cpu_max = _read(cgroup / "cpu.max")
        tasks_max = _read(cgroup / "pids.max")
    except ResourceLimitError:
        return False
    return (
        memory_max != "max"
        and memory_swap_max == "0"
        and not cpu_max.startswith("max ")
        and tasks_max != "max"
    )


def require_active_resource_scope() -> None:
    """Refuse an unbounded worker-heavy invocation."""
    if not active_resource_scope():
        raise ResourceLimitError(
            "worker-heavy command is not inside a finite no-swap resource "
            "scope; run it through scripts/resource_limited.py")


_SIZE = re.compile(r"^(?P<number>[0-9]+)(?P<unit>[KMG]?)$")


def _bytes(value: str) -> int:
    match = _SIZE.fullmatch(value)
    if match is None:
        raise ResourceLimitError(f"unsupported cgroup memory value {value!r}")
    scale = {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}
    return int(match["number"]) * scale[match["unit"]]


def _cpu_max(value: str) -> str:
    match = re.fullmatch(r"([0-9]+)%", value)
    if match is None:
        raise ResourceLimitError(f"unsupported CPU quota {value!r}")
    quota = int(match[1])
    period = 100_000
    return f"{period * quota // 100} {period}"


def _seconds(value: str) -> float:
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)s", value)
    if match is None:
        raise ResourceLimitError(f"unsupported runtime value {value!r}")
    return float(match[1])


def _configure_cgroup(path: Path, limits: ResourceLimits) -> None:
    values = {
        "memory.high": str(_bytes(limits.memory_high)),
        "memory.max": str(_bytes(limits.memory_max)),
        "memory.swap.max": str(_bytes(limits.memory_swap_max)),
        "cpu.max": _cpu_max(limits.cpu_quota),
        "pids.max": str(limits.tasks_max),
    }
    try:
        path.mkdir()
    except FileExistsError:
        raise
    except OSError as exc:
        raise ResourceLimitError(
            f"cannot create delegated cgroup {path}: {exc}") from exc
    try:
        for name, value in values.items():
            (path / name).write_text(value)
        (path / "memory.oom.group").write_text("1")
    except OSError as exc:
        try:
            path.rmdir()
        except OSError:
            pass
        raise ResourceLimitError(
            f"cannot configure delegated cgroup {path}: {exc}") from exc


def _create_cgroup(limits: ResourceLimits) -> Path:
    parent = _self_cgroup()
    if not (parent / "cgroup.procs").exists():
        raise ResourceLimitError(
            f"current cgroup is not a usable cgroup v2 parent: {parent}")
    if not (parent / "memory.max").exists() or not (parent / "cpu.max").exists():
        raise ResourceLimitError(
            f"current cgroup does not expose memory and CPU controllers: "
            f"{parent}")
    for _ in range(5):
        path = parent / f"nbdsl-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        try:
            _configure_cgroup(path, limits)
            return path
        except FileExistsError:
            continue
    raise ResourceLimitError("cannot allocate a unique delegated cgroup")


def _join(path: Path) -> None:
    try:
        (path / "cgroup.procs").write_text(str(os.getpid()))
    except OSError as exc:
        os.write(2, f"resource cgroup join failed: {exc}\n".encode())
        os._exit(126)


def _cleanup_cgroup(path: Path) -> None:
    try:
        members = _read(path / "cgroup.procs")
        if members:
            (path / "cgroup.kill").write_text("1")
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and _read(path / "cgroup.procs"):
                time.sleep(0.05)
        path.rmdir()
    except OSError as exc:
        raise ResourceLimitError(
            f"cannot clean up resource cgroup {path}: {exc}") from exc


def _stop_systemd_scope(unit: str) -> None:
    systemctl = shutil.which("systemctl")
    if systemctl is None:
        return
    try:
        subprocess.run(
            [systemctl, "--user", "stop", unit],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _run_in_cgroup(command: Sequence[str],
                   limits: ResourceLimits) -> int:
    path = _create_cgroup(limits)
    proc: subprocess.Popen[bytes] | None = None
    env = os.environ.copy()
    env["NBDSL_RESOURCE_LIMITED"] = "1"
    env["LEAN_NUM_THREADS"] = "1"
    received_signal: int | None = None

    def stop_on_signal(signum: int, _frame: object) -> None:
        nonlocal received_signal
        received_signal = signum
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    old_handlers: dict[int, signal.Handlers] = {}
    try:
        for signum in (signal.SIGINT, signal.SIGHUP, signal.SIGTERM):
            old_handlers[signum] = signal.signal(signum, stop_on_signal)
        proc = subprocess.Popen(
            list(command),
            env=env,
            preexec_fn=lambda: _join(path),
            start_new_session=True,
        )
        try:
            result = proc.wait(timeout=_seconds(limits.runtime_max))
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            result = 124
    finally:
        for signum, handler in old_handlers.items():
            signal.signal(signum, handler)
        if proc is not None and proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
        _cleanup_cgroup(path)
    if received_signal is not None:
        return 128 + received_signal
    return result


def _run_in_systemd_scope(command: Sequence[str],
                          limits: ResourceLimits) -> int:
    unit = f"nbdsl-resource-{os.getpid()}-{uuid.uuid4().hex[:8]}.scope"
    env = os.environ.copy()
    env["NBDSL_RESOURCE_LIMITED"] = "1"
    env["LEAN_NUM_THREADS"] = "1"
    proc: subprocess.Popen[bytes] | None = None
    received_signal: int | None = None

    def stop_on_signal(signum: int, _frame: object) -> None:
        nonlocal received_signal
        received_signal = signum
        _stop_systemd_scope(unit)

    old_handlers: dict[int, signal.Handlers] = {}
    try:
        proc = subprocess.Popen(
            systemd_command(command, limits, unit=unit),
            env=env,
        )
        for signum in (signal.SIGINT, signal.SIGHUP, signal.SIGTERM):
            old_handlers[signum] = signal.signal(signum, stop_on_signal)
        result = proc.wait()
    finally:
        for signum, handler in old_handlers.items():
            signal.signal(signum, handler)
        if proc is not None and proc.poll() is None:
            _stop_systemd_scope(unit)
            proc.wait()
    if received_signal is not None:
        return 128 + received_signal
    return result


def _systemd_scope_usable(limits: ResourceLimits) -> bool:
    systemd = shutil.which("systemd-run")
    if systemd is None:
        return False
    try:
        probe = subprocess.run(
            [systemd, *systemd_command(["true"], limits)[1:]],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


def run_limited(command: Sequence[str],
                limits: ResourceLimits = TEST_LIMITS) -> int:
    """Run a command under a hard cgroup boundary or fail closed."""
    if not command:
        raise ValueError("resource-limited command cannot be empty")
    env = os.environ.copy()
    env["NBDSL_RESOURCE_LIMITED"] = "1"
    env["LEAN_NUM_THREADS"] = "1"
    if active_resource_scope():
        return subprocess.run(list(command), check=False, env=env).returncode
    if _systemd_scope_usable(limits):
        return _run_in_systemd_scope(command, limits)
    return _run_in_cgroup(command, limits)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--" not in args:
        raise SystemExit("usage: resource_limited.py [--qualification] -- COMMAND")
    separator = args.index("--")
    options, command = args[:separator], args[separator + 1:]
    if not command:
        raise SystemExit("resource-limited command cannot be empty")
    unknown = [option for option in options if option != "--qualification"]
    if unknown:
        raise SystemExit(f"unknown option: {unknown[0]}")
    limits = QUALIFICATION_LIMITS if "--qualification" in options else TEST_LIMITS
    return run_limited(command, limits)


if __name__ == "__main__":
    raise SystemExit(main())
