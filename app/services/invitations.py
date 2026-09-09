from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from dataclasses import dataclass, replace
from typing import Callable, TypeVar


class InvitationError(RuntimeError):
    pass


class InvalidInvitation(InvitationError):
    pass


class InvitationGone(InvitationError):
    pass


class InvitationBusy(InvitationError):
    pass


class NoActiveInvitation(InvitationError):
    pass


@dataclass(frozen=True)
class ActiveInvitation:
    token: str
    nonce: str
    expires_at: int
    flow_id: str | None = None


T = TypeVar("T")


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError) as exc:
        raise InvalidInvitation from exc


class InvitationManager:
    VERSION = "v1"

    def __init__(
        self,
        *,
        ttl_seconds: int = 300,
        clock: Callable[[], float] = time.time,
        random_bytes: Callable[[int], bytes] = secrets.token_bytes,
        flow_factory: Callable[[], str] | None = None,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._random_bytes = random_bytes
        self._flow_factory = flow_factory or (lambda: secrets.token_urlsafe(32))
        self._secret = random_bytes(32)
        self._active: ActiveInvitation | None = None
        self._lock = threading.RLock()

    def create(self) -> ActiveInvitation:
        with self._lock:
            self._prune()
            if self._active is not None:
                raise InvitationBusy
            nonce = _encode(self._random_bytes(24))
            expires_at = int(self._clock()) + self._ttl_seconds
            payload = self._canonical_payload(nonce, expires_at)
            signature = hmac.digest(self._secret, payload, hashlib.sha256)
            token = f"{self.VERSION}.{_encode(payload)}.{_encode(signature)}"
            self._active = ActiveInvitation(
                token=token,
                nonce=nonce,
                expires_at=expires_at,
            )
            return self._active

    def current(self) -> ActiveInvitation | None:
        with self._lock:
            self._prune()
            return self._active

    def remaining_seconds(self, invitation: ActiveInvitation) -> int:
        return max(0, invitation.expires_at - int(self._clock()))

    def validate(self, token: str) -> ActiveInvitation:
        with self._lock:
            nonce, expires_at = self._verify_token(token)
            if expires_at <= self._clock():
                self._active = None
                raise InvitationGone
            if (
                self._active is None
                or self._active.nonce != nonce
                or not hmac.compare_digest(self._active.token, token)
            ):
                raise InvitationGone
            return self._active

    def claim(self, token: str, flow_id: str | None) -> str:
        with self._lock:
            active = self.validate(token)
            if active.flow_id is None:
                new_flow_id = self._flow_factory()
                self._active = replace(active, flow_id=new_flow_id)
                return new_flow_id
            if flow_id and hmac.compare_digest(active.flow_id, flow_id):
                return active.flow_id
            raise InvitationBusy

    def require_flow(self, token: str, flow_id: str) -> ActiveInvitation:
        with self._lock:
            active = self.validate(token)
            if active.flow_id is None or not hmac.compare_digest(active.flow_id, flow_id):
                raise InvitationBusy
            return active

    def consume(self, token: str, flow_id: str) -> None:
        with self._lock:
            self.require_flow(token, flow_id)
            self._active = None

    def complete(self, token: str, flow_id: str, operation: Callable[[], T]) -> T:
        with self._lock:
            self.require_flow(token, flow_id)
            result = operation()
            self._active = None
            return result

    def _verify_token(self, token: str) -> tuple[str, int]:
        try:
            version, encoded_payload, encoded_signature = token.split(".")
        except ValueError as exc:
            raise InvalidInvitation from exc
        if version != self.VERSION:
            raise InvalidInvitation

        payload = _decode(encoded_payload)
        signature = _decode(encoded_signature)
        expected = hmac.digest(self._secret, payload, hashlib.sha256)
        if not hmac.compare_digest(signature, expected):
            raise InvalidInvitation

        try:
            decoded = json.loads(payload)
            nonce = decoded["nonce"]
            expires_at = decoded["expires_at"]
            if (
                decoded.get("version") != 1
                or not isinstance(nonce, str)
                or not isinstance(expires_at, int)
                or payload != self._canonical_payload(nonce, expires_at)
            ):
                raise ValueError
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise InvalidInvitation from exc
        return nonce, expires_at

    @staticmethod
    def _canonical_payload(nonce: str, expires_at: int) -> bytes:
        return json.dumps(
            {"expires_at": expires_at, "nonce": nonce, "version": 1},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def _prune(self) -> None:
        if self._active is not None and self._active.expires_at <= self._clock():
            self._active = None
