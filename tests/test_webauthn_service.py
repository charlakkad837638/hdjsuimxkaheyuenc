import pytest

from app.services.credentials import CredentialRecord
from app.services.webauthn_service import WebAuthnFailure, WebAuthnService


def test_options_require_discoverable_user_verified_credentials() -> None:
    service = WebAuthnService(
        rp_id="door.example.ts.net",
        expected_origin="https://door.example.ts.net",
    )

    registration, registration_challenge = service.registration_options(
        user_id=b"u" * 32,
        display_name="Akira",
        exclude_credential_ids=[b"existing"],
    )
    authentication, authentication_challenge = service.authentication_options()

    assert registration["authenticatorSelection"]["residentKey"] == "required"
    assert registration["authenticatorSelection"]["userVerification"] == "required"
    assert registration["attestation"] == "none"
    assert registration["excludeCredentials"]
    assert authentication["allowCredentials"] == []
    assert authentication["userVerification"] == "required"
    assert len(registration_challenge) == 32
    assert len(authentication_challenge) == 32


def test_authentication_rejects_wrong_discoverable_user_handle() -> None:
    service = WebAuthnService(
        rp_id="door.example.ts.net",
        expected_origin="https://door.example.ts.net",
    )
    record = CredentialRecord(
        user_id=b"expected",
        display_name="Akira",
        credential_id=b"credential",
        credential_public_key=b"public-key",
        sign_count=0,
        transports=(),
        created_at="now",
    )

    with pytest.raises(WebAuthnFailure, match="userHandle"):
        service.verify_authentication(
            credential={"response": {"userHandle": "d3Jvbmc"}},
            expected_challenge=b"challenge",
            record=record,
        )
