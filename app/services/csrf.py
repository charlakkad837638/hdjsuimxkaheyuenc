from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable


class CsrfError(RuntimeError):
    pass


class InvalidCsrfToken(CsrfError):
    pass


class CsrfCapacityReached(CsrfError):
    pass


@dataclass(frozen=True)
class _CsrfRecord:
    peer_ip: str
    expires_at: float


class CsrfManager:
    def __init__(
        self,
        *,
        ttl_seconds: int = 600,
        capacity: int = 128,
        clock: Callable[[], float] = time.time,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._capacity = capacity
        self._clock = clock
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._records: dict[str, _CsrfRecord] = {}
        self._lock = threading.RLock()

    def issue(self, peer_ip: str) -> str:
        with self._lock:
            self._prune()
            if len(self._records) >= self._capacity:
                raise CsrfCapacityReached
            token = self._token_factory()
            self._records[token] = _CsrfRecord(
                peer_ip=peer_ip,
                expires_at=self._clock() + self._ttl_seconds,
            )
            return token

    def consume(self, token: str, peer_ip: str) -> None:
        with self._lock:
            self._prune()
            record = self._records.pop(token, None)
            if record is None or record.peer_ip != peer_ip:
                raise InvalidCsrfToken

    def _prune(self) -> None:
        now = self._clock()
        expired = [
            token for token, record in self._records.items() if record.expires_at <= now
        ]
        for token in expired:
            del self._records[token]
