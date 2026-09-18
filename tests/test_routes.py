from __future__ import annotations

import base64
import re

import pytest
from fastapi.testclient import TestClient

from app.dependencies import ServiceContainer
from app.services.credentials import CredentialRecord
from app.services.door_action import NoOpDoorAction


def basic_auth_header(username: str, password: str) -> str:
    encoded = base64.b64encode(f"{username}:{password}".encode("ascii")).decode("ascii")
    return f"Basic {encoded}"


def csrf_from(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def add_registered_user(services: ServiceContainer) -> CredentialRecord:
    record = CredentialRecord(
        user_id=b"user-id",
        display_name="Akira",
        credential_id=b"credential-id",
        credential_public_key=b"credential-public-key",
        sign_count=0,
        transports=("internal",),
        created_at="2026-01-01T00:00:00+00:00",
    )
    services.credentials.add(record)
    return record


def register_user(public_client: TestClient, services: ServiceContainer) -> None:
    token = services.invitations.create().token
    response = public_client.get("/new_user", params={"key": token})
    assert response.status_code == 200
    assert response.url.path == "/new_user"

    response = public_client.post(
        "/new_user/options",
        json={"display_name": "Akira"},
    )
    assert response.status_code == 200
    assert response.json()["user"]["displayName"] == "Akira"

    response = public_client.post(
        "/new_user/complete",
        json={"rawId": "fake-registration"},
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_public_pages_routes_and_security_headers(public_client: TestClient) -> None:
    assert public_client.get("/").status_code == 404
    assert public_client.get("/docs").status_code == 404
    assert public_client.get("/openapi.json").status_code == 404
    assert public_client.get("/door/").status_code == 404

    response = public_client.get("/door")
    assert response.status_code == 200
    assert "Open door" in response.text
    assert response.headers["cache-control"] == "no-store"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"

    static = public_client.get("/static/app.css")
    assert static.status_code == 200
    assert static.headers["content-type"].startswith("text/css")
    assert static.headers["cache-control"] == "public, max-age=300"
    assert public_client.get("/static/%2e%2e/server.py").status_code == 404


def test_untrusted_host_and_non_lan_admin_are_rejected(
    app,
    public_client: TestClient,
) -> None:
    rejected = public_client.get("/admin", headers={"accept": "text/html"})
    assert rejected.status_code == 404
    assert "www-authenticate" not in rejected.headers
    assert public_client.get("/door", headers={"host": "evil.example"}).status_code == 400

    with TestClient(
        app,
        base_url="http://door.local",
        client=("100.64.0.12", 50000),
    ) as tailscale_client:
        assert tailscale_client.get("/admin").status_code == 404


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/admin"),
        ("POST", "/admin/invitations"),
        ("GET", "/admin/invitation.svg"),
        ("POST", "/admin/users/delete"),
    ],
)
def test_admin_routes_require_basic_auth(app, method: str, path: str) -> None:
    with TestClient(
        app,
        base_url="http://door.local",
        client=("192.168.178.25", 50000),
    ) as client:
        response = client.request(method, path, headers={"accept": "text/html"})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Basic realm="Door admin"'


def test_admin_rejects_incorrect_basic_credentials(app) -> None:
    with TestClient(
        app,
        base_url="http://door.local",
        client=("192.168.178.25", 50000),
    ) as client:
        response = client.get(
            "/admin",
            headers={
                "accept": "text/html",
                "authorization": basic_auth_header("admin", "wrong-password"),
            },
        )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Basic realm="Door admin"'


def test_admin_creates_only_one_invitation_and_serves_qr(
    lan_client: TestClient,
    services: ServiceContainer,
) -> None:
    page = lan_client.get("/admin")
    assert page.status_code == 200
    token = csrf_from(page.text)

    created = lan_client.post(
        "/admin/invitations",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert created.status_code == 303
    assert created.headers["location"] == "/admin"

    qr = lan_client.get("/admin/invitation.svg")
    assert qr.status_code == 200
    assert qr.headers["content-type"].startswith("image/svg+xml")

    second_csrf = services.csrf.issue("192.168.178.25")
    duplicate = lan_client.post(
        "/admin/invitations",
        data={"csrf_token": second_csrf},
    )
    assert duplicate.status_code == 409


def test_admin_csrf_is_one_time_and_user_deletion_works(
    lan_client: TestClient,
    services: ServiceContainer,
) -> None:
    record = add_registered_user(services)
    page = lan_client.get("/admin")
    token = csrf_from(page.text)

    response = lan_client.post(
        "/admin/users/delete",
        data={
            "csrf_token": token,
            "user_id": "dXNlci1pZA",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert not services.credentials.has_credentials()

    replay = lan_client.post(
        "/admin/users/delete",
        data={
            "csrf_token": token,
            "user_id": "dXNlci1pZA",
        },
    )
    assert replay.status_code == 403


def test_invitation_cookie_registration_and_authentication_flow(
    public_client: TestClient,
    services: ServiceContainer,
) -> None:
    token = services.invitations.create().token
    landing = public_client.get(
        "/new_user",
        params={"key": token},
        follow_redirects=False,
    )
    assert landing.status_code == 303
    invite_cookie = landing.headers["set-cookie"]
    assert "door_invite=" in invite_cookie
    assert "HttpOnly" in invite_cookie
    assert "Secure" in invite_cookie
    assert "SameSite=lax" in invite_cookie

    public_client.follow_redirects = True
    assert public_client.get(landing.headers["location"]).status_code == 200

    options = public_client.post(
        "/new_user/options",
        json={"display_name": "Akira"},
    )
    assert options.status_code == 200
    assert "door_registration_flow=" in options.headers["set-cookie"]
    assert "SameSite=lax" in options.headers["set-cookie"]

    completed = public_client.post(
        "/new_user/complete",
        json={"rawId": "fake-registration"},
    )
    assert completed.status_code == 200
    assert services.credentials.has_credentials()
    assert services.invitations.current() is None

    auth_options = public_client.post("/open/options", json={})
    assert auth_options.status_code == 200
    assert auth_options.json()["allowCredentials"] == []
    assert "SameSite=strict" in auth_options.headers["set-cookie"]

    opened = public_client.post("/open", json={"rawId": "fake-authentication"})
    assert opened.status_code == 200
    assert opened.json() == {"ok": True}
    assert len(services.door_action.calls) == 1
    assert services.credentials.get_by_credential_id(b"credential-id").sign_count == 1


def test_registration_claim_blocks_a_second_browser(
    app,
    public_client: TestClient,
    services: ServiceContainer,
) -> None:
    token = services.invitations.create().token
    public_client.get("/new_user", params={"key": token})
    assert (
        public_client.post(
            "/new_user/options",
            json={"display_name": "First"},
        ).status_code
        == 200
    )

    with TestClient(
        app,
        base_url="https://door.example.ts.net",
        client=("127.0.0.1", 50001),
    ) as second_client:
        second_client.get("/new_user", params={"key": token})
        response = second_client.post(
            "/new_user/options",
            json={"display_name": "Second"},
        )
        assert response.status_code == 409


def test_invalid_authentication_never_invokes_action(
    public_client: TestClient,
    services: ServiceContainer,
) -> None:
    add_registered_user(services)
    assert public_client.post("/open/options", json={}).status_code == 200

    failed = public_client.post(
        "/open",
        json={"rawId": "fake-authentication", "invalid": True},
    )
    assert failed.status_code == 401
    assert services.door_action.calls == []

    replay = public_client.post(
        "/open",
        json={"rawId": "fake-authentication"},
    )
    assert replay.status_code == 400
    assert services.door_action.calls == []


def test_unknown_credential_and_action_failure_are_indistinguishable_until_verified(
    public_client: TestClient,
    services: ServiceContainer,
) -> None:
    add_registered_user(services)
    public_client.post("/open/options", json={})
    unknown = public_client.post("/open", json={"unknown": True})
    assert unknown.status_code == 401
    assert unknown.json()["error"]["code"] == "authentication_failed"

    public_client.post("/open/options", json={})
    services.door_action.error = RuntimeError("hardware unavailable")
    unavailable = public_client.post("/open", json={"rawId": "known"})
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "action_unavailable"
    assert services.door_action.calls == []


def test_request_body_limit(public_client: TestClient) -> None:
    response = public_client.post(
        "/open/options",
        content=b"x" * (64 * 1024 + 1),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413


def test_noop_door_action_has_no_state() -> None:
    action = NoOpDoorAction()
    assert action.execute(
        CredentialRecord(
            user_id=b"user",
            display_name="User",
            credential_id=b"credential",
            credential_public_key=b"key",
            sign_count=0,
            transports=(),
            created_at="now",
        )
    ) is None
    assert vars(action) == {}
