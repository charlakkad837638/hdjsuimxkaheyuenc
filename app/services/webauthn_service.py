from __future__ import annotations

import json
import hmac
import secrets
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.services.credentials import CredentialRecord, encode_base64url


class WebAuthnFailure(ValueError):
    pass


@dataclass(frozen=True)
class RegistrationResult:
    credential_id: bytes
    credential_public_key: bytes
    sign_count: int
    transports: tuple[str, ...]


class WebAuthnService:
    def __init__(self, *, rp_id: str, expected_origin: str, rp_name: str = "Door") -> None:
        self._rp_id = rp_id
        self._expected_origin = expected_origin
        self._rp_name = rp_name

    def registration_options(
        self,
        *,
        user_id: bytes,
        display_name: str,
        exclude_credential_ids: Sequence[bytes],
    ) -> tuple[dict[str, Any], bytes]:
        challenge = secrets.token_bytes(32)
        options = generate_registration_options(
            rp_id=self._rp_id,
            rp_name=self._rp_name,
            user_id=user_id,
            user_name=encode_base64url(user_id),
            user_display_name=display_name,
            challenge=challenge,
            timeout=60_000,
            attestation=AttestationConveyancePreference.NONE,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED,
                require_resident_key=True,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
            exclude_credentials=[
                PublicKeyCredentialDescriptor(id=credential_id)
                for credential_id in exclude_credential_ids
            ],
        )
        return json.loads(options_to_json(options)), challenge

    def verify_registration(
        self,
        *,
        credential: Mapping[str, Any],
        expected_challenge: bytes,
    ) -> RegistrationResult:
        try:
            verification = verify_registration_response(
                credential=dict(credential),
                expected_challenge=expected_challenge,
                expected_rp_id=self._rp_id,
                expected_origin=self._expected_origin,
                require_user_verification=True,
            )
        except (WebAuthnException, ValueError, TypeError) as exc:
            raise WebAuthnFailure("Registration verification failed") from exc

        response = credential.get("response")
        raw_transports = response.get("transports", []) if isinstance(response, Mapping) else []
        allowed_transports = {transport.value for transport in AuthenticatorTransport}
        transports = tuple(
            transport
            for transport in raw_transports
            if isinstance(transport, str) and transport in allowed_transports
        )
        return RegistrationResult(
            credential_id=verification.credential_id,
            credential_public_key=verification.credential_public_key,
            sign_count=verification.sign_count,
            transports=transports,
        )

    def authentication_options(self) -> tuple[dict[str, Any], bytes]:
        challenge = secrets.token_bytes(32)
        options = generate_authentication_options(
            rp_id=self._rp_id,
            challenge=challenge,
            timeout=60_000,
            allow_credentials=None,
            user_verification=UserVerificationRequirement.REQUIRED,
        )
        return json.loads(options_to_json(options)), challenge

    def credential_id_from_assertion(self, credential: Mapping[str, Any]) -> bytes:
        raw_id = credential.get("rawId")
        if not isinstance(raw_id, str):
            raise WebAuthnFailure("Authentication credential is missing rawId")
        try:
            return base64url_to_bytes(raw_id)
        except (ValueError, TypeError) as exc:
            raise WebAuthnFailure("Authentication credential has an invalid rawId") from exc

    def verify_authentication(
        self,
        *,
        credential: Mapping[str, Any],
        expected_challenge: bytes,
        record: CredentialRecord,
    ) -> int:
        response = credential.get("response")
        user_handle = response.get("userHandle") if isinstance(response, Mapping) else None
        if not isinstance(user_handle, str):
            raise WebAuthnFailure("Authentication credential is missing userHandle")
        try:
            decoded_user_handle = base64url_to_bytes(user_handle)
        except (ValueError, TypeError) as exc:
            raise WebAuthnFailure("Authentication credential has an invalid userHandle") from exc
        if not hmac.compare_digest(decoded_user_handle, record.user_id):
            raise WebAuthnFailure("Authentication userHandle does not match credential")

        try:
            verification = verify_authentication_response(
                credential=dict(credential),
                expected_challenge=expected_challenge,
                expected_rp_id=self._rp_id,
                expected_origin=self._expected_origin,
                credential_public_key=record.credential_public_key,
                credential_current_sign_count=record.sign_count,
                require_user_verification=True,
            )
        except (WebAuthnException, ValueError, TypeError) as exc:
            raise WebAuthnFailure("Authentication verification failed") from exc
        return verification.new_sign_count
