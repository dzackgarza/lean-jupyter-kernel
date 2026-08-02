"""Length-prefixed framed-JSON reply decoding."""

from __future__ import annotations

import json
import os
import select
import time

import psutil

from .errors import WorkerDied

RawFrame = dict[str, object]

LIVENESS_SLICE = 5.0  # reply-wait slice between worker liveness probes


def process_running(pid: int) -> bool:
    """Use psutil's required cross-platform process status authority.

    PID existence alone is insufficient because zombies still exist. Missing
    and zombie processes are dead; access or observation failures propagate
    because liveness cannot be inferred honestly without this capability.
    """
    try:
        status = psutil.Process(pid).status()
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return False
    return status not in {psutil.STATUS_DEAD, psutil.STATUS_ZOMBIE}


class FrameReader:
    """One incremental decoder state for a length-prefixed reply stream."""

    def __init__(self, fd: int) -> None:
        self.fd = fd
        self.buf = b""
        self.frame_length: int | None = None

    def read_frame(self, timeout: float, process_pid: int) -> RawFrame:
        deadline = time.monotonic() + timeout
        while True:
            if self.frame_length is None and b"\n" in self.buf:
                line, self.buf = self.buf.split(b"\n", 1)
                self.frame_length = int(line)
            if (self.frame_length is not None
                    and len(self.buf) >= self.frame_length):
                length = self.frame_length
                payload, self.buf = self.buf[:length], self.buf[length:]
                self.frame_length = None
                frame: RawFrame = json.loads(payload)
                return frame
            self._fill(deadline, process_pid)

    def _fill(self, deadline: float, process_pid: int) -> None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("timed out waiting for worker reply")
        ready, _, _ = select.select(
            [self.fd], [], [], min(LIVENESS_SLICE, remaining))
        if not ready:
            if not process_running(process_pid):
                raise WorkerDied(f"worker process {process_pid} is gone")
            return
        chunk = os.read(self.fd, 65536)
        if not chunk:
            raise WorkerDied("worker closed the reply channel")
        self.buf += chunk
