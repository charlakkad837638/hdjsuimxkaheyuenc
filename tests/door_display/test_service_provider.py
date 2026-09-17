from __future__ import annotations

import subprocess
from typing import Sequence

from door_display.models import UNKNOWN_TEXT, ValueState
from door_display.providers.service import ServiceProvider


class FakeRunner:
    def __init__(self, result: subprocess.CompletedProcess[str]) -> None:
        self.result = result
        self.calls: list[tuple[tuple[str, ...], float]] = []

    def __call__(
        self,
        args: Sequence[str],
        *,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((tuple(args), timeout))
        return self.result


def result(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        "systemctl",
        returncode,
        stdout=stdout,
        stderr="failed" if returncode else "",
    )


def test_service_provider_reads_requested_properties() -> None:
    runner = FakeRunner(
        result(
            "ActiveState=active\n"
            "SubState=running\n"
            "ActiveEnterTimestampMonotonic=900000000\n"
            "NRestarts=2\n"
        )
    )
    provider = ServiceProvider(runner=runner, clock=lambda: 1000.0)

    snapshot = provider.read_status()

    assert snapshot.state.text == "active"
    assert snapshot.process.text == "running"
    assert snapshot.uptime.text == "1m"
    assert snapshot.restarts.text == "2"
    command, timeout = runner.calls[0]
    assert timeout == 1.0
    assert "--property=ActiveState" in command
    assert "--property=NRestarts" in command


def test_inactive_service_has_human_readable_uptime() -> None:
    provider = ServiceProvider(
        runner=FakeRunner(
            result(
                "ActiveState=inactive\n"
                "SubState=dead\n"
                "ActiveEnterTimestampMonotonic=0\n"
                "NRestarts=0\n"
            )
        )
    )

    snapshot = provider.read_status()

    assert snapshot.state.text == "inactive"
    assert snapshot.process.text == "dead"
    assert snapshot.uptime.text == "not running"
    assert snapshot.restarts.text == "0"


def test_malformed_service_field_does_not_hide_valid_fields() -> None:
    provider = ServiceProvider(
        runner=FakeRunner(
            result(
                "ActiveState=active\n"
                "SubState=running\n"
                "ActiveEnterTimestampMonotonic=900000000\n"
                "NRestarts=invalid\n"
            )
        ),
        clock=lambda: 1000.0,
    )

    snapshot = provider.read_status()

    assert snapshot.state.text == "active"
    assert snapshot.process.text == "running"
    assert snapshot.uptime.text == "1m"
    assert snapshot.restarts.state is ValueState.UNKNOWN
    assert snapshot.restarts.text == UNKNOWN_TEXT


def test_failed_systemctl_marks_all_service_fields_unknown() -> None:
    provider = ServiceProvider(runner=FakeRunner(result("", returncode=1)))

    snapshot = provider.read_status()

    assert all(
        value.text == UNKNOWN_TEXT
        for value in (
            snapshot.state,
            snapshot.process,
            snapshot.uptime,
            snapshot.restarts,
        )
    )
