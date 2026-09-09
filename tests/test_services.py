from __future__ import annotations

import json
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from app.services.challenges import (
    ChallengeCapacityReached,
    ChallengeNotFound,
    ChallengeStore,
)
from app.services.credentials import (
    CorruptCredentialStore,
    CredentialRecord,
    CredentialStore,
)
from app.services.csrf import CsrfManager, InvalidCsrfToken
from app.services.invitations import (
    InvalidInvitation,
    InvitationBusy,
    InvitationGone,
    InvitationManager,
)


class FakeClock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def make_record(index: int = 1) -> CredentialRecord:
    return CredentialRecord(
        user_id=f"user-{index}".encode(),
        display_name=f"User {index}",
        credential_id=f"credential-{index}".encode(),
        credential_public_key=f"key-{index}".encode(),
        sign_count=0,
        transports=("internal",),
        created_at="2026-01-01T00:00:00+00:00",
    )


def test_credential_store_persists_updates_and_deletion(tmp_path: Path) -> None:
    store = CredentialStore(tmp_path)
    record = make_record()
    store.add(record)

    updated = store.verify_and_update(record.credential_id, lambda current: 7)
    assert updated.sign_count == 7
    assert CredentialStore(tmp_path).get_by_credential_id(record.credential_id).sign_count == 7

    store.delete(record.user_id)
    assert not CredentialStore(tmp_path).has_credentials()
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600


def test_credential_store_rejects_corruption(tmp_path: Path) -> None:
    store = CredentialStore(tmp_path)
    store.path.write_text("{broken", encoding="utf-8")

    with pytest.raises(CorruptCredentialStore):
        CredentialStore(tmp_path)


def test_concurrent_credential_writes_remain_valid(tmp_path: Path) -> None:
    store = CredentialStore(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda index: store.add(make_record(index)), range(1, 9)))

    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert len(CredentialStore(tmp_path).list_records()) == 8


def test_invitation_is_signed_claimed_once_and_expires() -> None:
    clock = FakeClock()
    manager = InvitationManager(
        clock=clock,
        random_bytes=lambda size: b"x" * size,
        flow_factory=lambda: "flow-one",
    )
    invitation = manager.create()

    with pytest.raises(InvitationBusy):
        manager.create()
    with pytest.raises(InvalidInvitation):
        manager.validate(invitation.token + "tampered")

    assert manager.claim(invitation.token, None) == "flow-one"
    assert manager.claim(invitation.token, "flow-one") == "flow-one"
    with pytest.raises(InvitationBusy):
        manager.claim(invitation.token, None)

    clock.now += 301
    with pytest.raises(InvitationGone):
        manager.validate(invitation.token)


def test_two_invitation_claims_cannot_both_win() -> None:
    manager = InvitationManager()
    token = manager.create().token
    barrier = Barrier(2)

    def claim() -> str:
        barrier.wait()
        try:
            return manager.claim(token, None)
        except InvitationBusy:
            return "busy"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: claim(), range(2)))

    assert results.count("busy") == 1


def test_challenges_are_bounded_expiring_and_single_use() -> None:
    clock = FakeClock()
    store = ChallengeStore(
        ttl_seconds=10,
        capacity=1,
        clock=clock,
        token_factory=lambda: "transaction",
    )
    assert store.issue(b"one") == "transaction"
    with pytest.raises(ChallengeCapacityReached):
        store.issue(b"two", key="other")
    assert store.consume("transaction").challenge == b"one"
    with pytest.raises(ChallengeNotFound):
        store.consume("transaction")

    store.issue(b"three")
    clock.now += 11
    with pytest.raises(ChallengeNotFound):
        store.consume("transaction")


def test_csrf_is_bound_to_peer_and_consumed_once() -> None:
    manager = CsrfManager(token_factory=lambda: "csrf")
    token = manager.issue("192.168.178.2")

    with pytest.raises(InvalidCsrfToken):
        manager.consume(token, "192.168.178.3")
    with pytest.raises(InvalidCsrfToken):
        manager.consume(token, "192.168.178.2")
