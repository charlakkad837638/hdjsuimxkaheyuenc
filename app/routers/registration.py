from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Cookie, Depends, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.dependencies import (
    get_credentials,
    get_invitations,
    get_registration_challenges,
    get_webauthn,
)
from app.errors import AppError
from app.services.challenges import (
    ChallengeCapacityReached,
    ChallengeNotFound,
    ChallengeStore,
)
from app.services.credentials import (
    CredentialRecord,
    CredentialStore,
    DuplicateCredential,
    DuplicateDisplayName,
)
from app.services.invitations import (
    ActiveInvitation,
    InvalidInvitation,
    InvitationBusy,
    InvitationGone,
    InvitationManager,
)
from app.services.webauthn_service import WebAuthnFailure, WebAuthnService
from app.views import TEMPLATES


router = APIRouter()


class RegistrationOptionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=64)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("display_name cannot be blank")
        return value


def _validate_invitation(
    invitations: InvitationManager,
    token: str | None,
    *,
    html: bool = False,
) -> ActiveInvitation:
    if not token:
        raise AppError(404, "invitation_invalid", "Invitation not found", html=html)
    try:
        return invitations.validate(token)
    except InvalidInvitation as exc:
        raise AppError(404, "invitation_invalid", "Invitation not found", html=html) from exc
    except InvitationGone as exc:
        raise AppError(410, "invitation_gone", "Invitation has expired or was used", html=html) from exc


@router.get("/new_user")
def new_user_page(
    request: Request,
    key: str | None = Query(default=None),
    door_invite: str | None = Cookie(default=None),
    invitations: InvitationManager = Depends(get_invitations),
):
    if key is not None:
        invitation = _validate_invitation(invitations, key, html=True)
        response = RedirectResponse("/new_user", status_code=303)
        response.set_cookie(
            "door_invite",
            key,
            max_age=invitations.remaining_seconds(invitation),
            secure=True,
            httponly=True,
            samesite="lax",
            path="/new_user",
        )
        return response

    _validate_invitation(invitations, door_invite, html=True)
    return TEMPLATES.TemplateResponse(request=request, name="new_user.html")


@router.post("/new_user/options")
def registration_options(
    payload: RegistrationOptionsRequest,
    door_invite: str | None = Cookie(default=None),
    door_registration_flow: str | None = Cookie(default=None),
    credentials: CredentialStore = Depends(get_credentials),
    invitations: InvitationManager = Depends(get_invitations),
    challenges: ChallengeStore = Depends(get_registration_challenges),
    webauthn: WebAuthnService = Depends(get_webauthn),
):
    invitation = _validate_invitation(invitations, door_invite)
    if credentials.display_name_exists(payload.display_name):
        raise AppError(409, "display_name_exists", "That display name is already registered")

    try:
        flow_id = invitations.claim(door_invite or "", door_registration_flow)
    except InvitationBusy as exc:
        raise AppError(
            409,
            "registration_busy",
            "Another registration is already in progress",
        ) from exc

    user_id = secrets.token_bytes(32)
    options, challenge = webauthn.registration_options(
        user_id=user_id,
        display_name=payload.display_name,
        exclude_credential_ids=[
            record.credential_id for record in credentials.list_records()
        ],
    )
    try:
        challenges.issue(
            challenge,
            key=flow_id,
            data={"user_id": user_id, "display_name": payload.display_name},
        )
    except ChallengeCapacityReached as exc:
        raise AppError(
            503,
            "registration_busy",
            "Registration service is busy",
        ) from exc

    response = JSONResponse(options)
    response.set_cookie(
        "door_registration_flow",
        flow_id,
        max_age=invitations.remaining_seconds(invitation),
        secure=True,
        httponly=True,
        samesite="lax",
        path="/new_user",
    )
    return response


@router.post("/new_user/complete")
def registration_complete(
    credential: dict[str, Any],
    door_invite: str | None = Cookie(default=None),
    door_registration_flow: str | None = Cookie(default=None),
    credentials: CredentialStore = Depends(get_credentials),
    invitations: InvitationManager = Depends(get_invitations),
    challenges: ChallengeStore = Depends(get_registration_challenges),
    webauthn: WebAuthnService = Depends(get_webauthn),
):
    _validate_invitation(invitations, door_invite)
    if not door_registration_flow:
        raise AppError(
            400,
            "registration_transaction_missing",
            "Registration transaction is missing or expired",
        )
    try:
        invitations.require_flow(door_invite or "", door_registration_flow)
    except InvitationBusy as exc:
        raise AppError(
            409,
            "registration_busy",
            "Another registration is already in progress",
        ) from exc
    try:
        transaction = challenges.consume(door_registration_flow)
    except ChallengeNotFound as exc:
        raise AppError(
            400,
            "registration_transaction_missing",
            "Registration transaction is missing or expired",
        ) from exc

    user_id = transaction.data.get("user_id")
    display_name = transaction.data.get("display_name")
    if not isinstance(user_id, bytes) or not isinstance(display_name, str):
        raise AppError(400, "registration_failed", "Registration state is invalid")

    try:
        verification = webauthn.verify_registration(
            credential=credential,
            expected_challenge=transaction.challenge,
        )
    except WebAuthnFailure as exc:
        raise AppError(400, "registration_failed", "Passkey registration failed") from exc

    record = CredentialRecord(
        user_id=user_id,
        display_name=display_name,
        credential_id=verification.credential_id,
        credential_public_key=verification.credential_public_key,
        sign_count=verification.sign_count,
        transports=verification.transports,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    try:
        invitations.complete(
            door_invite or "",
            door_registration_flow,
            lambda: credentials.add(record),
        )
    except DuplicateDisplayName as exc:
        raise AppError(
            409,
            "display_name_exists",
            "That display name is already registered",
        ) from exc
    except DuplicateCredential as exc:
        raise AppError(
            409,
            "credential_exists",
            "That passkey is already registered",
        ) from exc
    except InvitationGone as exc:
        raise AppError(
            410,
            "invitation_gone",
            "Invitation has expired or was used",
        ) from exc

    response = JSONResponse({"ok": True})
    response.delete_cookie("door_invite", path="/new_user", secure=True, httponly=True)
    response.delete_cookie(
        "door_registration_flow",
        path="/new_user",
        secure=True,
        httponly=True,
    )
    return response
