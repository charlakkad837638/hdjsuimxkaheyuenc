from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("PUBLIC_ORIGIN", "https://door.example.ts.net")
os.environ.setdefault("ADMIN_HOSTS", "door.local")
os.environ.setdefault("DATA_DIR", "/tmp/door-tests")

from app.config import Settings
from app.dependencies import ServiceContainer
from app.main import create_app
from app.services.challenges import ChallengeStore
from app.services.credentials import CredentialRecord, CredentialStore
from app.services.csrf import CsrfManager
from app.services.invitations import InvitationManager
from app.services.webauthn_service import RegistrationResult, WebAuthnFailure


class FakeWebAuthn:
    credential_id = b"credential-id"
    credential_public_key = b"credential-public-key"

    def registration_options(
        self,
        *,
        user_id: bytes,
        display_name: str,
        exclude_credential_ids: Sequence[bytes],
    ) -> tuple[dict[str, Any], bytes]:
        del exclude_credential_ids
        return (
            {
                "challenge": "cmVnaXN0cmF0aW9u",
                "rp": {"id": "door.example.ts.net", "name": "Door"},
                "user": {
                    "id": "dXNlcg",
                    "name": "dXNlcg",
                    "displayName": display_name,
                },
                "pubKeyCredParams": [],
                "excludeCredentials": [],
            },
            b"registration-challenge",
        )

    def verify_registration(
        self,
        *,
        credential: Mapping[str, Any],
        expected_challenge: bytes,
    ) -> RegistrationResult:
        assert expected_challenge == b"registration-challenge"
        if credential.get("invalid"):
            raise WebAuthnFailure
        return RegistrationResult(
            credential_id=self.credential_id,
            credential_public_key=self.credential_public_key,
            sign_count=0,
            transports=("internal",),
        )

    def authentication_options(self) -> tuple[dict[str, Any], bytes]:
        return (
            {
                "challenge": "YXV0aGVudGljYXRpb24",
                "rpId": "door.example.ts.net",
                "allowCredentials": [],
                "userVerification": "required",
            },
            b"authentication-challenge",
        )

    def credential_id_from_assertion(self, credential: Mapping[str, Any]) -> bytes:
        if credential.get("unknown"):
            return b"unknown"
        return self.credential_id

    def verify_authentication(
        self,
        *,
        credential: Mapping[str, Any],
        expected_challenge: bytes,
        record: CredentialRecord,
    ) -> int:
        assert expected_challenge == b"authentication-challenge"
        if credential.get("invalid"):
            raise WebAuthnFailure
        return record.sign_count + 1


class SpyDoorAction:
    def __init__(self) -> None:
        self.calls: list[CredentialRecord] = []
        self.error: Exception | None = None

    def execute(self, authenticated_user: CredentialRecord) -> None:
        if self.error is not None:
            raise self.error
        self.calls.append(authenticated_user)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings.from_env(
        {
            "PUBLIC_ORIGIN": "https://door.example.ts.net",
            "ADMIN_HOSTS": "door.local",
            "LAN_CIDR": "192.168.178.0/24",
            "DATA_DIR": str(tmp_path),
        }
    )


@pytest.fixture
def services(settings: Settings) -> ServiceContainer:
    return ServiceContainer(
        credentials=CredentialStore(settings.data_dir),
        invitations=InvitationManager(),
        csrf=CsrfManager(),
        authentication_challenges=ChallengeStore(capacity=128),
        registration_challenges=ChallengeStore(capacity=1),
        webauthn=FakeWebAuthn(),
        door_action=SpyDoorAction(),
    )


@pytest.fixture
def app(settings: Settings, services: ServiceContainer):
    return create_app(settings, services)


@pytest.fixture
def public_client(app):
    with TestClient(
        app,
        base_url="https://door.example.ts.net",
        client=("127.0.0.1", 50000),
    ) as client:
        yield client


@pytest.fixture
def lan_client(app):
    with TestClient(
        app,
        base_url="http://door.local",
        client=("192.168.178.25", 50000),
    ) as client:
        yield client
