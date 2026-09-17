from __future__ import annotations

import re
import time
from typing import Callable

from door_display.models import ServiceSnapshot, StatusValue, ValueState, format_duration
from door_display.providers.common import (
    COMMAND_TIMEOUT_SECONDS,
    CommandRunner,
    command_failure,
    run_command,
)


SYSTEMD_TOKEN = re.compile(r"[a-z][a-z0-9-]*")


class ServiceProvider:
    def __init__(
        self,
        *,
        service_name: str = "webserver.service",
        runner: CommandRunner = run_command,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.service_name = service_name
        self.runner = runner
        self.clock = clock

    def read_status(self) -> ServiceSnapshot:
        args = (
            "systemctl",
            "show",
            self.service_name,
            "--no-pager",
            "--property=ActiveState",
            "--property=SubState",
            "--property=ActiveEnterTimestampMonotonic",
            "--property=NRestarts",
        )
        try:
            result = self.runner(args, timeout=COMMAND_TIMEOUT_SECONDS)
            if result.returncode != 0:
                return self._all_unknown(command_failure("systemctl show", result))
            properties, duplicates = self._parse_properties(result.stdout)
        except Exception as exc:
            return self._all_unknown(self._reason("systemctl show", exc))

        state = self._state_value(properties, duplicates, "ActiveState")
        process = self._state_value(properties, duplicates, "SubState")
        restarts = self._restart_value(properties, duplicates)
        uptime = self._uptime_value(properties, duplicates, state)
        return ServiceSnapshot(
            state=state,
            process=process,
            uptime=uptime,
            restarts=restarts,
        )

    @staticmethod
    def _parse_properties(contents: str) -> tuple[dict[str, str], set[str]]:
        properties: dict[str, str] = {}
        duplicates: set[str] = set()
        for line in contents.splitlines():
            if not line:
                continue
            key, separator, value = line.partition("=")
            if not separator or not key:
                continue
            if key in properties:
                duplicates.add(key)
            properties[key] = value
        return properties, duplicates

    @staticmethod
    def _state_value(
        properties: dict[str, str],
        duplicates: set[str],
        name: str,
    ) -> StatusValue:
        try:
            if name in duplicates:
                raise ValueError(f"{name} is duplicated")
            value = properties[name]
            if not SYSTEMD_TOKEN.fullmatch(value):
                raise ValueError(f"{name} is not a valid state token")
            return StatusValue.known(value)
        except Exception as exc:
            return StatusValue.unknown(ServiceProvider._reason(name, exc))

    @staticmethod
    def _restart_value(
        properties: dict[str, str],
        duplicates: set[str],
    ) -> StatusValue:
        try:
            name = "NRestarts"
            if name in duplicates:
                raise ValueError(f"{name} is duplicated")
            restarts = int(properties[name])
            if restarts < 0:
                raise ValueError("NRestarts is negative")
            return StatusValue.known(str(restarts))
        except Exception as exc:
            return StatusValue.unknown(ServiceProvider._reason("NRestarts", exc))

    def _uptime_value(
        self,
        properties: dict[str, str],
        duplicates: set[str],
        state: StatusValue,
    ) -> StatusValue:
        if state.state is ValueState.UNKNOWN:
            return StatusValue.unknown("unable to calculate service uptime: state is unknown")
        if state.text != "active":
            return StatusValue.known("not running")

        try:
            name = "ActiveEnterTimestampMonotonic"
            if name in duplicates:
                raise ValueError(f"{name} is duplicated")
            started_microseconds = int(properties[name])
            now_microseconds = round(self.clock() * 1_000_000)
            if started_microseconds <= 0 or now_microseconds < started_microseconds:
                raise ValueError("active timestamp is internally inconsistent")
            return StatusValue.known(
                format_duration((now_microseconds - started_microseconds) / 1_000_000)
            )
        except Exception as exc:
            return StatusValue.unknown(
                self._reason("ActiveEnterTimestampMonotonic", exc)
            )

    @staticmethod
    def _all_unknown(reason: str) -> ServiceSnapshot:
        value = StatusValue.unknown(reason)
        return ServiceSnapshot(
            state=value,
            process=value,
            uptime=value,
            restarts=value,
        )

    @staticmethod
    def _reason(source: str, exc: Exception) -> str:
        detail = str(exc).strip()
        suffix = f": {detail}" if detail else ""
        return f"unable to read {source} ({type(exc).__name__}{suffix})"
