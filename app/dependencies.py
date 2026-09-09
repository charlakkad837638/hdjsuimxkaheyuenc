from __future__ import annotations

import ipaddress
from dataclasses import dataclass

from fastapi import Depends, Request

from app.config import Settings
from app.errors import AppError
from app.services.challenges import ChallengeStore
from app.services.credentials import CredentialStore
from app.services.csrf import CsrfManager
from app.services.door_action import DoorAction, NoOpDoorAction
from app.services.invitations import InvitationManager
from app.services.webauthn_service import WebAuthnService


@dataclass
class ServiceContainer:
    credentials: CredentialStore
    invitations: InvitationManager
    csrf: CsrfManager
    authentication_challenges: ChallengeStore
    registration_challenges: ChallengeStore
    webauthn: WebAuthnService
    door_action: DoorAction


def build_services(settings: Settings) -> ServiceContainer:
    return ServiceContainer(
        credentials=CredentialStore(settings.data_dir),
        invitations=InvitationManager(),
        csrf=CsrfManager(),
        authentication_challenges=ChallengeStore(capacity=128),
        registration_challenges=ChallengeStore(capacity=1),
        webauthn=WebAuthnService(
            rp_id=settings.rp_id,
            expected_origin=settings.public_origin,
        ),
        door_action=NoOpDoorAction(),
    )


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_services(request: Request) -> ServiceContainer:
    return request.app.state.services


def get_credentials(
    services: ServiceContainer = Depends(get_services),
) -> CredentialStore:
    return services.credentials


def get_invitations(
    services: ServiceContainer = Depends(get_services),
) -> InvitationManager:
    return services.invitations


def get_csrf(services: ServiceContainer = Depends(get_services)) -> CsrfManager:
    return services.csrf


def get_authentication_challenges(
    services: ServiceContainer = Depends(get_services),
) -> ChallengeStore:
    return services.authentication_challenges


def get_registration_challenges(
    services: ServiceContainer = Depends(get_services),
) -> ChallengeStore:
    return services.registration_challenges


def get_webauthn(
    services: ServiceContainer = Depends(get_services),
) -> WebAuthnService:
    return services.webauthn


def get_door_action(
    services: ServiceContainer = Depends(get_services),
) -> DoorAction:
    return services.door_action


def require_lan_admin(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> str:
    if request.client is None:
        raise AppError(404, "not_found", "Not found", html=True)
    try:
        address = ipaddress.ip_address(request.client.host.split("%", 1)[0])
    except ValueError as exc:
        raise AppError(404, "not_found", "Not found", html=True) from exc

    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    if address.is_loopback or address not in settings.lan_network:
        raise AppError(404, "not_found", "Not found", html=True)
    return str(address)
