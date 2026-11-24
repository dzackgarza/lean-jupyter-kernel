"""Process management and framed-JSON transport for the nbdsl worker.

Owns everything fd-shaped: pipe setup, capturing `lake env` then spawning
`nbdsl_worker` as the owned child, the length-prefixed frame codec,
stdout/stderr pump threads, exact request controls, and explicit shutdown. The kernel
class never touches fds.
"""

from .client import WorkerClient
from .errors import (
    WorkerDied,
    WorkerInterrupted,
    WorkerUnavailable,
    WireProtocolError,
    check_wire_protocol,
)
from .resolve import find_worker_exe, lake_env

__all__ = [
    "WorkerClient",
    "WorkerDied",
    "WorkerInterrupted",
    "WorkerUnavailable",
    "WireProtocolError",
    "check_wire_protocol",
    "find_worker_exe",
    "lake_env",
]
