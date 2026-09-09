from __future__ import annotations

import base64
import json
import os
import tempfile
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable


class CredentialStoreError(RuntimeError):
    pass


class CorruptCredentialStore(CredentialStoreError):
    pass


class DuplicateDisplayName(CredentialStoreError):
    pass


class DuplicateCredential(CredentialStoreError):
    pass


class CredentialNotFound(CredentialStoreError):
    pass


def encode_base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def decode_base64url(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except (ValueError, TypeError) as exc:
        raise CorruptCredentialStore("Invalid base64url value in credential store") from exc


@dataclass(frozen=True)
class CredentialRecord:
    user_id: bytes
    display_name: str
    credential_id: bytes
    credential_public_key: bytes
    sign_count: int
    transports: tuple[str, ...]
    created_at: str

    def to_json(self) -> dict[str, object]:
        return {
            "user_id": encode_base64url(self.user_id),
            "display_name": self.display_name,
            "credential_id": encode_base64url(self.credential_id),
            "credential_public_key": encode_base64url(self.credential_public_key),
            "sign_count": self.sign_count,
            "transports": list(self.transports),
            "created_at": self.created_at,
        }

    @classmethod
    def from_json(cls, value: object) -> "CredentialRecord":
        if not isinstance(value, dict):
            raise CorruptCredentialStore("Credential record must be an object")
        try:
            display_name = value["display_name"]
            sign_count = value["sign_count"]
            transports = value.get("transports", [])
            created_at = value["created_at"]
            if not isinstance(display_name, str) or not display_name:
                raise TypeError
            if not isinstance(sign_count, int) or sign_count < 0:
                raise TypeError
            if not isinstance(transports, list) or not all(
                isinstance(item, str) for item in transports
            ):
                raise TypeError
            if not isinstance(created_at, str) or not created_at:
                raise TypeError
            return cls(
                user_id=decode_base64url(value["user_id"]),
                display_name=display_name,
                credential_id=decode_base64url(value["credential_id"]),
                credential_public_key=decode_base64url(value["credential_public_key"]),
                sign_count=sign_count,
                transports=tuple(transports),
                created_at=created_at,
            )
        except (KeyError, TypeError) as exc:
            raise CorruptCredentialStore("Credential record has an invalid schema") from exc


class CredentialStore:
    VERSION = 1

    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / "credentials.json"
        self._lock = threading.RLock()
        data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self._lock:
            if self._path.exists():
                self._records = self._load()
            else:
                self._records: list[CredentialRecord] = []
                self._write()

    @property
    def path(self) -> Path:
        return self._path

    def list_records(self) -> tuple[CredentialRecord, ...]:
        with self._lock:
            return tuple(
                sorted(self._records, key=lambda record: record.display_name.casefold())
            )

    def has_credentials(self) -> bool:
        with self._lock:
            return bool(self._records)

    def display_name_exists(self, display_name: str) -> bool:
        normalized = display_name.casefold()
        with self._lock:
            return any(record.display_name.casefold() == normalized for record in self._records)

    def add(self, record: CredentialRecord) -> None:
        with self._lock:
            if any(
                existing.display_name.casefold() == record.display_name.casefold()
                for existing in self._records
            ):
                raise DuplicateDisplayName(record.display_name)
            if any(
                existing.credential_id == record.credential_id for existing in self._records
            ):
                raise DuplicateCredential
            self._records.append(record)
            self._write()

    def delete(self, user_id: bytes) -> CredentialRecord:
        with self._lock:
            for index, record in enumerate(self._records):
                if record.user_id == user_id:
                    deleted = self._records.pop(index)
                    self._write()
                    return deleted
            raise CredentialNotFound

    def get_by_credential_id(self, credential_id: bytes) -> CredentialRecord:
        with self._lock:
            for record in self._records:
                if record.credential_id == credential_id:
                    return record
            raise CredentialNotFound

    def verify_and_update(
        self,
        credential_id: bytes,
        verifier: Callable[[CredentialRecord], int],
    ) -> CredentialRecord:
        with self._lock:
            for index, record in enumerate(self._records):
                if record.credential_id != credential_id:
                    continue
                new_sign_count = verifier(record)
                if not isinstance(new_sign_count, int) or new_sign_count < 0:
                    raise CredentialStoreError("Verifier returned an invalid sign count")
                updated = replace(record, sign_count=new_sign_count)
                if updated != record:
                    self._records[index] = updated
                    self._write()
                return updated
            raise CredentialNotFound

    def _load(self) -> list[CredentialRecord]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CorruptCredentialStore(
                f"Could not read credential store: {self._path}"
            ) from exc
        if not isinstance(raw, dict) or raw.get("version") != self.VERSION:
            raise CorruptCredentialStore("Unsupported credential store schema")
        users = raw.get("users")
        if not isinstance(users, list):
            raise CorruptCredentialStore("Credential store users must be a list")
        records = [CredentialRecord.from_json(value) for value in users]
        if len({record.user_id for record in records}) != len(records):
            raise CorruptCredentialStore("Credential store has duplicate user IDs")
        if len({record.credential_id for record in records}) != len(records):
            raise CorruptCredentialStore("Credential store has duplicate credential IDs")
        if len({record.display_name.casefold() for record in records}) != len(records):
            raise CorruptCredentialStore("Credential store has duplicate display names")
        return records

    def _write(self) -> None:
        payload = {
            "version": self.VERSION,
            "users": [record.to_json() for record in self._records],
        }
        descriptor, temp_name = tempfile.mkstemp(
            dir=self._path.parent,
            prefix=".credentials-",
            suffix=".tmp",
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temp_name, 0o600)
            os.replace(temp_name, self._path)
            directory_fd = os.open(self._path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
