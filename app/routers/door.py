from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Cookie, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.dependencies import (
    get_authentication_challenges,
    get_credentials,
    get_door_action,
    get_webauthn,
)
from app.errors import AppError
from app.services.challenges import (
    ChallengeCapacityReached,
    ChallengeNotFound,
    ChallengeStore,
)
from app.services.credentials import CredentialNotFound, CredentialStore
from app.services.door_action import DoorAction
from app.services.webauthn_service import WebAuthnFailure, WebAuthnService
from app.views import TEMPLATES


router = APIRouter()


class EmptyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


@router.get("/door")
def door_page(request: Request):
    return TEMPLATES.TemplateResponse(request=request, name="door.html")


@router.post("/open/options")
def authentication_options(
    payload: EmptyPayload,
    request: Request,
    credentials: CredentialStore = Depends(get_credentials),
    challenges: ChallengeStore = Depends(get_authentication_challenges),
    webauthn: WebAuthnService = Depends(get_webauthn),
):
    del payload
    if not credentials.has_credentials():
        raise AppError(409, "no_credentials", "No passkeys have been registered")

    challenges.discard(request.cookies.get("door_auth_tx"))
    options, challenge = webauthn.authentication_options()
    try:
        transaction_id = challenges.issue(challenge)
    except ChallengeCapacityReached as exc:
        raise AppError(
            503,
            "authentication_busy",
            "Too many authentication attempts are active",
        ) from exc

    response = JSONResponse(options)
    response.set_cookie(
        "door_auth_tx",
        transaction_id,
        max_age=120,
        secure=True,
        httponly=True,
        samesite="strict",
        path="/open",
    )
    return response


@router.post("/open")
def open_door(
    credential: dict[str, Any],
    door_auth_tx: str | None = Cookie(default=None),
    credentials: CredentialStore = Depends(get_credentials),
    challenges: ChallengeStore = Depends(get_authentication_challenges),
    webauthn: WebAuthnService = Depends(get_webauthn),
    door_action: DoorAction = Depends(get_door_action),
):
    if not door_auth_tx:
        raise AppError(
            400,
            "authentication_transaction_missing",
            "Authentication transaction is missing or expired",
        )
    try:
        transaction = challenges.consume(door_auth_tx)
    except ChallengeNotFound as exc:
        raise AppError(
            400,
            "authentication_transaction_missing",
            "Authentication transaction is missing or expired",
        ) from exc

    try:
        credential_id = webauthn.credential_id_from_assertion(credential)
        record = credentials.verify_and_update(
            credential_id,
            lambda stored: webauthn.verify_authentication(
                credential=credential,
                expected_challenge=transaction.challenge,
                record=stored,
            ),
        )
    except (CredentialNotFound, WebAuthnFailure) as exc:
        raise AppError(
            401,
            "authentication_failed",
            "Passkey authentication failed",
        ) from exc

    try:
        door_action.execute(record)
    except Exception as exc:
        raise AppError(
            503,
            "action_unavailable",
            "Authentication succeeded but the door action is unavailable",
        ) from exc

    response = JSONResponse({"ok": True})
    response.delete_cookie("door_auth_tx", path="/open", secure=True, httponly=True)
    return response
