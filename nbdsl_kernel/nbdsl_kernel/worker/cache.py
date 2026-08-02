"""Olean session-cache save/restore for REPL recovery."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from ..protocol import LOAD_SESSION_REPLY, SAVE_SESSION_REPLY, LoadSessionOk, SaveSessionOk
from .errors import CACHE_RESTORE_TIMEOUT, REPLY_TIMEOUT, WorkerDied
from .frames import RawFrame


class SessionCacheMixin:
    """Mixin: persist and restore committed REPL state via oleans.

    Concrete clients must provide ``cache_dir``, ``prelude``, ``ledger``,
    ``snapshot``, ``on_stream``, ``_request``, and ``kill``.
    """

    cache_dir: str | None
    prelude: str
    ledger: list[tuple[str, str]]
    snapshot: int
    on_stream: Callable[[str, str], None]

    def _request(self, op: str, payload: RawFrame,
                 timeout: float = REPLY_TIMEOUT) -> RawFrame:
        raise NotImplementedError

    def kill(self) -> None:
        raise NotImplementedError

    def _ledger_key(self) -> str:
        h = hashlib.sha256(self.prelude.encode())
        for _, code in self.ledger:
            h.update(b"\x00" + code.encode())
        return h.hexdigest()

    def _cache_descriptor(self) -> dict[str, str]:
        assert self.cache_dir is not None
        root = Path(self.cache_dir)
        head = (root / "module.txt").read_text().strip()

        def digest(path: Path) -> str:
            with path.open("rb") as stream:
                return hashlib.file_digest(stream, "sha256").hexdigest()

        return {
            "ledger": self._ledger_key(),
            "head": head,
            "olean_sha256": digest(root / f"{head}.olean"),
            "scope_sha256": digest(root / "scope.json"),
        }

    def save_session(self) -> None:
        """Persist committed state after a REPL commit (cheap: the olean holds
        only session-local constants + extension entries)."""
        if self.cache_dir is None:
            return
        try:
            rep = SAVE_SESSION_REPLY.validate_python(self._request(
                "save_session", {"path": str(self.cache_dir)}, timeout=60))
        except (WorkerDied, TimeoutError) as e:
            # Not fatal — the ledger still describes the state — but silence
            # here makes the later replay look inexplicable. Name the cause.
            self.on_stream("stderr", f"session cache not saved: {e}\n")
            return
        key = Path(self.cache_dir) / "key.txt"
        if isinstance(rep, SaveSessionOk) and rep.saved:
            key.write_text(json.dumps(self._cache_descriptor(), sort_keys=True))
        else:
            # Uncacheable state (open scopes, syntax-valued options, …):
            # drop the key so restart falls back to replay.
            key.unlink(missing_ok=True)

    def _try_restore_session(self) -> bool:
        if self.cache_dir is None:
            return False
        key = Path(self.cache_dir) / "key.txt"
        if not key.exists():
            return False
        try:
            recorded = json.loads(key.read_text())
            if recorded != self._cache_descriptor():
                return False
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False
        # Past this point the key matched, so a miss is something going wrong
        # rather than ordinary uncacheable state: say what, then replay.
        try:
            rep = LOAD_SESSION_REPLY.validate_python(self._request(
                "load_session", {"path": str(self.cache_dir)},
                timeout=CACHE_RESTORE_TIMEOUT))
        except TimeoutError:
            self.on_stream(
                "stderr",
                "session cache restore timed out after "
                f"{CACHE_RESTORE_TIMEOUT:g}s; discarding worker before replay\n",
            )
            self.kill()
            return False
        except WorkerDied as e:
            self.on_stream("stderr", f"session cache not restored: {e}\n")
            self.kill()
            return False
        if not isinstance(rep, LoadSessionOk):
            self.on_stream("stderr",
                           f"session cache not restored: {rep.message}\n")
            return False
        self.snapshot = rep.snapshot
        return True
