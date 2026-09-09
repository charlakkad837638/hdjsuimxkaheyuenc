from __future__ import annotations

from typing import Protocol

from app.services.credentials import CredentialRecord


class DoorAction(Protocol):
    def execute(self, authenticated_user: CredentialRecord) -> None: ...


class NoOpDoorAction:
    def execute(self, authenticated_user: CredentialRecord) -> None:
        return None
