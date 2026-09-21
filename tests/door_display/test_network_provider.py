from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Sequence

from door_display.models import UNKNOWN_TEXT
from door_display.providers.network import NetworkProvider


class FakeRunner:
    def __init__(
        self,
        results: dict[str, subprocess.CompletedProcess[str] | Exception],
    ) -> None:
        self.results = results
        self.calls: list[tuple[tuple[str, ...], float]] = []

    def __call__(
        self,
        args: Sequence[str],
        *,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        command = tuple(args)
        self.calls.append((command, timeout))
        result = self.results[command[0]]
        if isinstance(result, Exception):
            raise result
        return result


def completed(command: str, stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr="")


def test_network_provider_reads_wifi_and_lan() -> None:
    values = {
        Path("/sys/class/net/wlan0/operstate"): "up\n",
        Path("/proc/net/wireless"): (
            "Inter-| sta\n face |\n"
            " wlan0: 0000   62.  -57.  -256        0      0      0      0      0\n"
        ),
    }
    runner = FakeRunner(
        {
            "ip": completed(
                "ip",
                "3: wlan0 inet 192.168.178.33/24 brd 192.168.178.255 scope global wlan0\n",
            ),
        }
    )
    provider = NetworkProvider(reader=values.__getitem__, runner=runner)

    assert provider.read_wifi().text == "-57 dBm"
    assert provider.read_lan().text == "192.168.178.33"
    assert all(timeout == 1.0 for _command, timeout in runner.calls)


def test_known_network_absences_are_human_readable() -> None:
    values = {
        Path("/sys/class/net/wlan0/operstate"): "down\n",
    }
    runner = FakeRunner(
        {
            "ip": completed("ip"),
        }
    )
    provider = NetworkProvider(reader=values.__getitem__, runner=runner)

    assert provider.read_wifi().text == "down"
    assert provider.read_lan().text == "no address"


def test_command_timeout_is_unknown() -> None:
    runner = FakeRunner(
        {
            "ip": subprocess.TimeoutExpired("ip", timeout=1),
        }
    )
    provider = NetworkProvider(reader=lambda _path: "", runner=runner)

    assert provider.read_lan().text == UNKNOWN_TEXT


def test_linked_wifi_without_signal_is_connected() -> None:
    def reader(path: Path) -> str:
        if path.name == "operstate":
            return "up\n"
        raise OSError("wireless statistics unavailable")

    assert NetworkProvider(reader=reader).read_wifi().text == "connected"
