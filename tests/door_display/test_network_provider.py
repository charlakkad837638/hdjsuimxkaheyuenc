from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Sequence

from door_display.models import UNKNOWN_TEXT, ValueState
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


def test_network_provider_reads_wifi_lan_and_tailscale() -> None:
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
            "tailscale": completed(
                "tailscale",
                json.dumps(
                    {
                        "BackendState": "Running",
                        "Self": {"Online": True},
                        "TailscaleIPs": ["100.64.1.2", "fd7a:115c:a1e0::1"],
                    }
                ),
            ),
        }
    )
    provider = NetworkProvider(reader=values.__getitem__, runner=runner)

    assert provider.read_wifi().text == "-57 dBm"
    assert provider.read_lan().text == "192.168.178.33"
    state, address = provider.read_tailscale()
    assert state.text == "connected"
    assert address.text == "100.64.1.2"
    assert all(timeout == 1.0 for _command, timeout in runner.calls)


def test_known_network_absences_are_human_readable() -> None:
    values = {
        Path("/sys/class/net/wlan0/operstate"): "down\n",
    }
    runner = FakeRunner(
        {
            "ip": completed("ip"),
            "tailscale": completed(
                "tailscale",
                json.dumps(
                    {
                        "BackendState": "Stopped",
                        "TailscaleIPs": [],
                    }
                ),
            ),
        }
    )
    provider = NetworkProvider(reader=values.__getitem__, runner=runner)

    assert provider.read_wifi().text == "down"
    assert provider.read_lan().text == "no address"
    state, address = provider.read_tailscale()
    assert state.text == "down"
    assert address.text == "no address"


def test_tailscale_fields_fail_independently() -> None:
    runner = FakeRunner(
        {
            "tailscale": completed(
                "tailscale",
                json.dumps(
                    {
                        "BackendState": "Unexpected",
                        "Self": {"Online": True},
                        "TailscaleIPs": ["100.64.2.3"],
                    }
                ),
            )
        }
    )
    provider = NetworkProvider(reader=lambda _path: "", runner=runner)

    state, address = provider.read_tailscale()
    assert state.state is ValueState.UNKNOWN
    assert state.text == UNKNOWN_TEXT
    assert address.text == "100.64.2.3"


def test_command_timeout_is_unknown() -> None:
    runner = FakeRunner(
        {
            "tailscale": subprocess.TimeoutExpired("tailscale", timeout=1),
        }
    )
    provider = NetworkProvider(reader=lambda _path: "", runner=runner)

    state, address = provider.read_tailscale()
    assert state.text == UNKNOWN_TEXT
    assert address.text == UNKNOWN_TEXT


def test_linked_wifi_without_signal_is_connected() -> None:
    def reader(path: Path) -> str:
        if path.name == "operstate":
            return "up\n"
        raise OSError("wireless statistics unavailable")

    assert NetworkProvider(reader=reader).read_wifi().text == "connected"
