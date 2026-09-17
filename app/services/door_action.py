from __future__ import annotations

import time
from collections.abc import Callable
from threading import Lock
from typing import Protocol

from gpiozero import OutputDevice

from app.services.credentials import CredentialRecord

RELAY_GPIO_BCM = 17
RELAY_PULSE_SECONDS = 5.0


class DoorAction(Protocol):
    def execute(self, authenticated_user: CredentialRecord) -> None: ...


class NoOpDoorAction:
    def execute(self, authenticated_user: CredentialRecord) -> None:
        return None


class RelayOutput(Protocol):
    def on(self) -> None: ...

    def off(self) -> None: ...

    def close(self) -> None: ...


class RelayDoorAction:
    """Momentarily close the active-high door relay after authentication."""

    def __init__(
        self,
        *,
        output_factory: Callable[..., RelayOutput] = OutputDevice,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._relay = output_factory(
            RELAY_GPIO_BCM,
            active_high=True,
            initial_value=False,
        )
        self._sleeper = sleeper
        self._lock = Lock()

    def execute(self, authenticated_user: CredentialRecord) -> None:
        del authenticated_user
        with self._lock:
            try:
                self._relay.on()
                self._sleeper(RELAY_PULSE_SECONDS)
            finally:
                self._relay.off()

    def close(self) -> None:
        with self._lock:
            try:
                self._relay.off()
            finally:
                self._relay.close()
