from __future__ import annotations

import ipaddress
import math
from pathlib import Path

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
    def _reason(source: str, exc: Exception) -> str:
        detail = str(exc).strip()
        suffix = f": {detail}" if detail else ""
        return f"unable to read {source} ({type(exc).__name__}{suffix})"
