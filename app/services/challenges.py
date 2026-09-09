from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable


class ChallengeError(RuntimeError):
    pass


class ChallengeNotFound(ChallengeError):
    pass


class ChallengeCapacityReached(ChallengeError):
    pass


@dataclass(frozen=True)
class ChallengeRecord:
    challenge: bytes
    data: dict[str, object]
    expires_at: float


class ChallengeStore:
    def __init__(
        self,
        *,
        ttl_seconds: int = 120,
        capacity: int = 128,
        clock: Callable[[], float] = time.time,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._capacity = capacity
        self._clock = clock
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._records: dict[str, ChallengeRecord] = {}
        self._lock = threading.RLock()

    def issue(
        self,
        challenge: bytes,
        *,
        data: dict[str, object] | None = None,
        key: str | None = None,
    ) -> str:
        with self._lock:
            self._prune()
            transaction_id = key or self._token_factory()
            if transaction_id not in self._records and len(self._records) >= self._capacity:
                raise ChallengeCapacityReached
            self._records[transaction_id] = ChallengeRecord(
                challenge=challenge,
                data=dict(data or {}),
                expires_at=self._clock() + self._ttl_seconds,
            )
            return transaction_id

    def consume(self, transaction_id: str) -> ChallengeRecord:
        with self._lock:
            self._prune()
            try:
                return self._records.pop(transaction_id)
            except KeyError as exc:
                raise ChallengeNotFound from exc

    def discard(self, transaction_id: str | None) -> None:
        if not transaction_id:
            return
        with self._lock:
            self._records.pop(transaction_id, None)

    def __len__(self) -> int:
        with self._lock:
            self._prune()
            return len(self._records)

    def _prune(self) -> None:
        now = self._clock()
        expired = [
            transaction_id
            for transaction_id, record in self._records.items()
            if record.expires_at <= now
        ]
        for transaction_id in expired:
            del self._records[transaction_id]
