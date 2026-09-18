from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from typing import Annotated
from urllib.parse import urlencode

import qrcode
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response
from qrcode.image.svg import SvgPathImage

from app.config import Settings
from app.dependencies import (
    get_credentials,
    get_csrf,
    get_invitations,
    get_settings,
    require_admin,
)
from app.errors import AppError
from app.services.credentials import (
    CredentialNotFound,
    CredentialStore,
    CredentialStoreError,
    decode_base64url,
    encode_base64url,
)
from app.services.csrf import (
    CsrfCapacityReached,
    CsrfManager,
    InvalidCsrfToken,
)
from app.services.invitations import (
    InvitationBusy,
    InvitationManager,
)
from app.views import TEMPLATES


router = APIRouter()


def _invitation_url(settings: Settings, token: str) -> str:
    return f"{settings.public_origin}/new_user?{urlencode({'key': token})}"


def _consume_csrf(csrf: CsrfManager, csrf_token: str, peer_ip: str) -> None:
    try:
        csrf.consume(csrf_token, peer_ip)
    except InvalidCsrfToken as exc:
        raise AppError(403, "csrf_invalid", "Form token is invalid or expired", html=True) from exc


@router.get("/admin")
def admin_page(
    request: Request,
    peer_ip: str = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    credentials: CredentialStore = Depends(get_credentials),
    invitations: InvitationManager = Depends(get_invitations),
    csrf: CsrfManager = Depends(get_csrf),
):
    try:
        csrf_token = csrf.issue(peer_ip)
    except CsrfCapacityReached as exc:
        raise AppError(503, "admin_busy", "Admin service is busy", html=True) from exc

    active = invitations.current()
    invitation = None
    if active is not None:
        invitation = {
            "url": _invitation_url(settings, active.token),
            "expires_at": datetime.fromtimestamp(
                active.expires_at,
                tz=timezone.utc,
            ).isoformat(),
            "claimed": active.flow_id is not None,
        }
    users = [
        {
            "user_id": encode_base64url(record.user_id),
            "display_name": record.display_name,
            "created_at": record.created_at,
        }
        for record in credentials.list_records()
    ]
    return TEMPLATES.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "users": users,
            "invitation": invitation,
            "csrf_token": csrf_token,
        },
    )


@router.post("/admin/invitations")
def create_invitation(
    csrf_token: Annotated[str, Form()],
    peer_ip: str = Depends(require_admin),
    csrf: CsrfManager = Depends(get_csrf),
    invitations: InvitationManager = Depends(get_invitations),
):
    _consume_csrf(csrf, csrf_token, peer_ip)
    try:
        invitations.create()
    except InvitationBusy as exc:
        raise AppError(
            409,
            "invitation_busy",
            "An invitation or registration is already active",
            html=True,
        ) from exc
    return RedirectResponse("/admin", status_code=303)


@router.get("/admin/invitation.svg")
def invitation_qr(
    _peer_ip: str = Depends(require_admin),
    settings: Settings = Depends(get_settings),
    invitations: InvitationManager = Depends(get_invitations),
):
    active = invitations.current()
    if active is None:
        raise AppError(404, "invitation_not_found", "No invitation is active")
    image = qrcode.make(
        _invitation_url(settings, active.token),
        image_factory=SvgPathImage,
    )
    output = BytesIO()
    image.save(output)
    return Response(output.getvalue(), media_type="image/svg+xml")


@router.post("/admin/users/delete")
def delete_user(
    csrf_token: Annotated[str, Form()],
    user_id: Annotated[str, Form()],
    peer_ip: str = Depends(require_admin),
    csrf: CsrfManager = Depends(get_csrf),
    credentials: CredentialStore = Depends(get_credentials),
):
    _consume_csrf(csrf, csrf_token, peer_ip)
    try:
        decoded_user_id = decode_base64url(user_id)
        if encode_base64url(decoded_user_id) != user_id:
            raise CredentialStoreError("Non-canonical user ID")
        credentials.delete(decoded_user_id)
    except (CredentialNotFound, CredentialStoreError) as exc:
        raise AppError(404, "user_not_found", "User not found", html=True) from exc
    return RedirectResponse("/admin", status_code=303)
