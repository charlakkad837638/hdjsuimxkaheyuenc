from __future__ import annotations

import ipaddress
import json
import math
from pathlib import Path
from typing import Any

from door_display.models import StatusValue
from door_display.providers.common import (
    COMMAND_TIMEOUT_SECONDS,
    CommandRunner,
    TextReader,
    command_failure,
    read_text,
    run_command,
)


KNOWN_DOWN_OPERSTATES = {
    "down",
    "dormant",
    "lowerlayerdown",
    "notpresent",
}
KNOWN_DOWN_TAILSCALE_STATES = {
    "NeedsLogin",
    "NeedsMachineAuth",
    "NoState",
    "Starting",
    "Stopped",
}


class NetworkProvider:
    def __init__(
        self,
        *,
        interface: str = "wlan0",
        reader: TextReader = read_text,
        runner: CommandRunner = run_command,
    ) -> None:
        self.interface = interface
        self.reader = reader
        self.runner = runner

    def read_wifi(self) -> StatusValue:
        operstate_path = Path(f"/sys/class/net/{self.interface}/operstate")
        try:
            operstate = self.reader(operstate_path).strip().lower()
        except Exception as exc:
            return StatusValue.unknown(self._reason(str(operstate_path), exc))

        if operstate in KNOWN_DOWN_OPERSTATES:
            return StatusValue.known("down")
        if operstate != "up":
            return StatusValue.unknown(
                f"unsupported {self.interface} operstate: {operstate or 'empty'}"
            )

        try:
            wireless = self.reader(Path("/proc/net/wireless"))
        except Exception:
            return StatusValue.known("connected")

        try:
            signal = self._wireless_signal(wireless)
        except Exception as exc:
            return StatusValue.unknown(self._reason("/proc/net/wireless", exc))
        if signal is None:
            return StatusValue.known("connected")
        return StatusValue.known(f"{round(signal)} dBm")

    def read_lan(self) -> StatusValue:
        args = (
            "ip",
            "-4",
            "-o",
            "address",
            "show",
            "dev",
            self.interface,
            "scope",
            "global",
        )
        try:
            result = self.runner(args, timeout=COMMAND_TIMEOUT_SECONDS)
            if result.returncode != 0:
                return StatusValue.unknown(command_failure("ip", result))

            for line in result.stdout.splitlines():
                fields = line.split()
                if "inet" not in fields:
                    continue
                index = fields.index("inet")
                if index + 1 >= len(fields):
                    raise ValueError("inet field has no address")
                address = ipaddress.ip_interface(fields[index + 1]).ip
                if isinstance(address, ipaddress.IPv4Address):
                    return StatusValue.known(str(address))
            return StatusValue.known("no address")
        except Exception as exc:
            return StatusValue.unknown(self._reason("ip", exc))

    def read_tailscale(self) -> tuple[StatusValue, StatusValue]:
        args = ("tailscale", "status", "--json")
        try:
            result = self.runner(args, timeout=COMMAND_TIMEOUT_SECONDS)
            if result.returncode != 0:
                reason = command_failure("tailscale status", result)
                return StatusValue.unknown(reason), StatusValue.unknown(reason)

            payload = json.loads(result.stdout)
            if not isinstance(payload, dict):
                raise ValueError("top-level status is not an object")
        except Exception as exc:
            reason = self._reason("tailscale status", exc)
            return StatusValue.unknown(reason), StatusValue.unknown(reason)

        return self._tailscale_state(payload), self._tailscale_ip(payload)

    def _wireless_signal(self, contents: str) -> float | None:
        for line in contents.splitlines():
            interface, separator, values = line.partition(":")
            if not separator or interface.strip() != self.interface:
                continue
            fields = values.split()
            if len(fields) < 3:
                raise ValueError("wireless row is missing signal fields")
            signal = float(fields[2])
            if not math.isfinite(signal):
                raise ValueError("wireless signal is not finite")
            return signal
        return None

    @staticmethod
    def _tailscale_state(payload: dict[str, Any]) -> StatusValue:
        try:
            backend_state = payload["BackendState"]
            if not isinstance(backend_state, str):
                raise ValueError("BackendState has the wrong type")
            if backend_state in KNOWN_DOWN_TAILSCALE_STATES:
                return StatusValue.known("down")
            if backend_state != "Running":
                raise ValueError(f"unsupported BackendState: {backend_state}")

            self_status = payload["Self"]
            if not isinstance(self_status, dict):
                raise ValueError("Self has the wrong type")
            online = self_status["Online"]
            if not isinstance(online, bool):
                raise ValueError("Self.Online has the wrong type")
            return StatusValue.known("connected" if online else "down")
        except Exception as exc:
            return StatusValue.unknown(NetworkProvider._reason("tailscale state", exc))

    @staticmethod
    def _tailscale_ip(payload: dict[str, Any]) -> StatusValue:
        try:
            addresses = payload["TailscaleIPs"]
            if not isinstance(addresses, list):
                raise ValueError("TailscaleIPs has the wrong type")
            if not addresses:
                return StatusValue.known("no address")

            saw_invalid = False
            for raw_address in addresses:
                if not isinstance(raw_address, str):
                    saw_invalid = True
                    continue
                try:
                    address = ipaddress.ip_address(raw_address)
                except ValueError:
                    saw_invalid = True
                    continue
                if isinstance(address, ipaddress.IPv4Address):
                    return StatusValue.known(str(address))

            if saw_invalid:
                raise ValueError("TailscaleIPs contains invalid addresses")
            return StatusValue.known("no address")
        except Exception as exc:
            return StatusValue.unknown(NetworkProvider._reason("tailscale IP", exc))

    @staticmethod
    def _reason(source: str, exc: Exception) -> str:
        detail = str(exc).strip()
        suffix = f": {detail}" if detail else ""
        return f"unable to read {source} ({type(exc).__name__}{suffix})"
