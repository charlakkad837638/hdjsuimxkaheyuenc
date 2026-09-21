from __future__ import annotations

import logging
from typing import Any

import pytest

from door_display.app import DisplayApplication, countdown_level
from door_display.config import DisplayConfig
from door_display.models import ServiceSnapshot, StatusValue


class FakeDisplay:
    width = 128
    height = 64

    def __init__(self) -> None:
        self.frames: list[Any] = []
        self.cleaned = False

    def display(self, image: Any) -> None:
        self.frames.append(image)

    def cleanup(self) -> None:
        self.cleaned = True


class FakeRenderer:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def render(self, page: Any, level: int) -> tuple[Any, int]:
        if self.fail:
            raise RuntimeError("render failed")
        return page, level


class FakeSystemProvider:
    def __init__(self) -> None:
        self.cpu_calls = 0
        self.memory_calls = 0
        self.uptime_calls = 0
        self.storage_calls = 0

    def read_cpu(self) -> StatusValue:
        self.cpu_calls += 1
        return StatusValue.known("10%")

    def read_memory(self) -> StatusValue:
        self.memory_calls += 1
        return StatusValue.known("20%")

    def read_uptime(self) -> StatusValue:
        self.uptime_calls += 1
        return StatusValue.known("1h 0m")

    def read_storage(self) -> StatusValue:
        self.storage_calls += 1
        return StatusValue.known("12.3G used / 45.7G free")


class FakeNetworkProvider:
    def __init__(self, wifi_values: list[StatusValue] | None = None) -> None:
        self.wifi_values = wifi_values or [StatusValue.known("connected")]
        self.wifi_calls = 0
        self.lan_calls = 0

    def read_wifi(self) -> StatusValue:
        value = self.wifi_values[min(self.wifi_calls, len(self.wifi_values) - 1)]
        self.wifi_calls += 1
        return value

    def read_lan(self) -> StatusValue:
        self.lan_calls += 1
        return StatusValue.known("192.168.1.2")


class FakeCloudflareProvider:
    def __init__(self) -> None:
        self.tunnel_calls = 0
        self.public_calls = 0

    def read_tunnel(self) -> StatusValue:
        self.tunnel_calls += 1
        return StatusValue.known("connected")

    def read_public(self) -> StatusValue:
        self.public_calls += 1
        return StatusValue.known("online")


class FakeServiceProvider:
    def __init__(self) -> None:
        self.calls = 0

    def read_status(self) -> ServiceSnapshot:
        self.calls += 1
        return ServiceSnapshot(
            state=StatusValue.known("active"),
            process=StatusValue.known("running"),
            uptime=StatusValue.known("1h 0m"),
            restarts=StatusValue.known("0"),
        )


class StopImmediately:
    def wait(self, _timeout: float) -> bool:
        return True


def make_application(
    *,
    display: FakeDisplay | None = None,
    renderer: FakeRenderer | None = None,
    network: FakeNetworkProvider | None = None,
    cloudflare: FakeCloudflareProvider | None = None,
    logger: logging.Logger | None = None,
) -> tuple[
    DisplayApplication,
    FakeDisplay,
    FakeSystemProvider,
    FakeNetworkProvider,
    FakeCloudflareProvider,
    FakeServiceProvider,
]:
    resolved_display = display or FakeDisplay()
    system = FakeSystemProvider()
    resolved_network = network or FakeNetworkProvider()
    resolved_cloudflare = cloudflare or FakeCloudflareProvider()
    service = FakeServiceProvider()
    app = DisplayApplication(
        config=DisplayConfig(page_seconds=4),
        display=resolved_display,
        renderer=renderer or FakeRenderer(),  # type: ignore[arg-type]
        system_provider=system,
        network_provider=resolved_network,
        cloudflare_provider=resolved_cloudflare,
        service_provider=service,
        stop_event=StopImmediately(),
        logger=logger,
    )
    return (
        app,
        resolved_display,
        system,
        resolved_network,
        resolved_cloudflare,
        service,
    )


def test_countdown_is_quantized_to_eight_levels() -> None:
    assert countdown_level(0, 4, 4) == 8
    assert countdown_level(0.5, 4, 4) == 7
    assert countdown_level(2, 4, 4) == 4
    assert countdown_level(3.9, 4, 4) == 1
    assert countdown_level(4, 4, 4) == 0


def test_application_rotates_pages_and_suppresses_duplicate_redraws() -> None:
    app, display, system, network, cloudflare, service = make_application()

    app.start(0)
    assert display.frames[-1][0].name == "NETWORK"
    assert display.frames[-1][1] == 8

    app.tick(0.5)
    assert display.frames[-1][1] == 7
    frame_count = len(display.frames)
    app.tick(0.6)
    assert len(display.frames) == frame_count

    app.tick(4)
    assert display.frames[-1][0].name == "SYSTEM"
    assert display.frames[-1][1] == 8
    app.tick(8)
    assert display.frames[-1][0].name == "WEBSERVER"
    app.tick(10)
    app.tick(12)
    assert display.frames[-1][0].name == "NETWORK"

    assert system.cpu_calls == 5
    assert system.memory_calls == 3
    assert system.uptime_calls == 3
    assert system.storage_calls == 1
    assert network.wifi_calls == 2
    assert network.lan_calls == 2
    assert cloudflare.tunnel_calls == 2
    assert cloudflare.public_calls == 1
    assert service.calls == 2


def test_page_deadline_catches_up_without_drift() -> None:
    app, _display, _system, _network, _cloudflare, _service = make_application()

    app.start(0)
    app.tick(12.1)

    assert app.active_page_index == 0
    assert app.page_deadline == 16


def test_public_health_refreshes_every_sixty_seconds() -> None:
    app, _display, _system, _network, cloudflare, _service = make_application()

    app.start(0)
    app.tick(10)
    assert cloudflare.tunnel_calls == 2
    assert cloudflare.public_calls == 1

    app.tick(60)
    assert cloudflare.tunnel_calls == 3
    assert cloudflare.public_calls == 2


def test_storage_refreshes_every_ten_minutes() -> None:
    app, _display, system, _network, _cloudflare, _service = make_application()

    app.start(0)
    app.tick(599.9)
    assert system.storage_calls == 1

    app.tick(600)
    assert system.storage_calls == 2

    app.tick(1200)
    assert system.storage_calls == 3


def test_unknown_failures_are_deduplicated_and_recovery_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("test-oled-transitions")
    network = FakeNetworkProvider(
        [
            StatusValue.unknown("wireless read failed"),
            StatusValue.unknown("wireless read failed"),
            StatusValue.known("down"),
        ]
    )
    app, _display, _system, _network, _cloudflare, _service = make_application(
        network=network,
        logger=logger,
    )

    with caplog.at_level(logging.INFO, logger=logger.name):
        app.start(0)
        app.tick(10)
        app.tick(20)

    assert caplog.text.count("WiFi is [UNKOWN]") == 1
    assert "WiFi recovered: down" in caplog.text
    assert "WiFi state: down" in caplog.text


def test_run_cleans_up_after_normal_stop() -> None:
    app, display, _system, _network, _cloudflare, _service = make_application()

    app.run()

    assert display.cleaned is True


def test_run_cleans_up_after_render_failure() -> None:
    display = FakeDisplay()
    app, _display, _system, _network, _cloudflare, _service = make_application(
        display=display,
        renderer=FakeRenderer(fail=True),
    )

    with pytest.raises(RuntimeError, match="render failed"):
        app.run()

    assert display.cleaned is True
