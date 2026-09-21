from __future__ import annotations

from typing import Any

import pytest

from app.services.credentials import CredentialRecord
from app.services.door_action import RELAY_PULSE_SECONDS, RelayDoorAction


class FakeRelayOutput:
    def __init__(self) -> None:
        self.events: list[str] = []

    def on(self) -> None:
        self.events.append("on")

    def off(self) -> None:
        self.events.append("off")

    def close(self) -> None:
        self.events.append("close")


def authenticated_user() -> CredentialRecord:
    return CredentialRecord(
        user_id=b"user",
        display_name="User",
        credential_id=b"credential",
        credential_public_key=b"key",
        sign_count=0,
        transports=(),
        created_at="now",
    )


def test_relay_uses_bcm17_active_high_and_pulses_for_configured_duration() -> None:
    relay = FakeRelayOutput()
    construction: dict[str, Any] = {}
    sleeps: list[float] = []

    def output_factory(pin: int, **kwargs: Any) -> FakeRelayOutput:
        construction.update(pin=pin, **kwargs)
        return relay

    action = RelayDoorAction(output_factory=output_factory, sleeper=sleeps.append)
    action.execute(authenticated_user())

    assert construction == {
        "pin": 17,
        "active_high": True,
        "initial_value": False,
    }
    assert sleeps == [RELAY_PULSE_SECONDS]
    assert relay.events == ["on", "off"]

    action.close()
    assert relay.events == ["on", "off", "off", "close"]


def test_relay_is_restored_low_when_the_pulse_fails() -> None:
    relay = FakeRelayOutput()

    def output_factory(pin: int, **kwargs: Any) -> FakeRelayOutput:
        del pin, kwargs
        return relay

    def failing_sleep(seconds: float) -> None:
        assert seconds == RELAY_PULSE_SECONDS
        raise RuntimeError("interrupted")

    action = RelayDoorAction(
        output_factory=output_factory,
        sleeper=failing_sleep,
    )

    with pytest.raises(RuntimeError, match="interrupted"):
        action.execute(authenticated_user())

    assert relay.events == ["on", "off"]
