from __future__ import annotations

from pathlib import Path

from door_display.models import MEASURING_TEXT, UNKNOWN_TEXT, ValueState
from door_display.providers.system import (
    PROC_MEMINFO,
    PROC_STAT,
    PROC_UPTIME,
    SystemProvider,
)


class MutableReader:
    def __init__(self, values: dict[Path, str]) -> None:
        self.values = values

    def __call__(self, path: Path) -> str:
        return self.values[path]


def test_system_provider_calculates_cpu_memory_and_uptime() -> None:
    reader = MutableReader(
        {
            PROC_STAT: "cpu 100 0 100 800 0 0 0 0\n",
            PROC_MEMINFO: "MemTotal: 1000 kB\nMemAvailable: 250 kB\n",
            PROC_UPTIME: "90061.00 0.00\n",
        }
    )
    provider = SystemProvider(reader=reader)

    first_cpu = provider.read_cpu()
    assert first_cpu.state is ValueState.MEASURING
    assert first_cpu.text == MEASURING_TEXT

    reader.values[PROC_STAT] = "cpu 150 0 150 900 0 0 0 0\n"
    assert provider.read_cpu().text == "50%"
    assert provider.read_memory().text == "75%"
    assert provider.read_uptime().text == "1d 1h"


def test_system_provider_returns_exact_unknown_for_bad_values() -> None:
    reader = MutableReader(
        {
            PROC_STAT: "cpu invalid\n",
            PROC_MEMINFO: "MemTotal: 0 kB\nMemAvailable: 1 kB\n",
            PROC_UPTIME: "-1 0\n",
        }
    )
    provider = SystemProvider(reader=reader)

    values = (
        provider.read_cpu(),
        provider.read_memory(),
        provider.read_uptime(),
    )
    assert all(value.state is ValueState.UNKNOWN for value in values)
    assert all(value.text == UNKNOWN_TEXT for value in values)
    assert all(value.error for value in values)


def test_cpu_counter_regression_is_unknown_then_recovers() -> None:
    reader = MutableReader({PROC_STAT: "cpu 10 0 10 80 0 0 0 0\n"})
    provider = SystemProvider(reader=reader)
    assert provider.read_cpu().state is ValueState.MEASURING

    reader.values[PROC_STAT] = "cpu 5 0 5 70 0 0 0 0\n"
    assert provider.read_cpu().state is ValueState.UNKNOWN

    reader.values[PROC_STAT] = "cpu 15 0 15 90 0 0 0 0\n"
    assert provider.read_cpu().text == "50%"
