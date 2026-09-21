from __future__ import annotations

from dataclasses import replace
import logging
import math
import signal
from threading import Event
import time
from types import FrameType
from typing import Callable, Protocol

from door_display.config import DisplayConfig, load_config
from door_display.device import DisplayDevice, create_device
from door_display.models import (
    NetworkSnapshot,
    ServiceSnapshot,
    StatusValue,
    SystemSnapshot,
    UNKNOWN_TEXT,
    ValueState,
)
from door_display.pages import build_pages
from door_display.renderer import COUNTDOWN_STEPS, DisplayRenderer


CPU_REFRESH_SECONDS = 2.0
SYSTEM_REFRESH_SECONDS = 5.0
STORAGE_REFRESH_SECONDS = 600.0
NETWORK_REFRESH_SECONDS = 10.0
TUNNEL_REFRESH_SECONDS = 10.0
PUBLIC_REFRESH_SECONDS = 60.0
SERVICE_REFRESH_SECONDS = 10.0
SCHEDULER_TICK_SECONDS = 0.5


class SystemStatusProvider(Protocol):
    def read_cpu(self) -> StatusValue: ...

    def read_memory(self) -> StatusValue: ...

    def read_uptime(self) -> StatusValue: ...

    def read_storage(self) -> StatusValue: ...


class NetworkStatusProvider(Protocol):
    def read_wifi(self) -> StatusValue: ...

    def read_lan(self) -> StatusValue: ...


class CloudflareStatusProvider(Protocol):
    def read_tunnel(self) -> StatusValue: ...

    def read_public(self) -> StatusValue: ...


class ServiceStatusProvider(Protocol):
    def read_status(self) -> ServiceSnapshot: ...


class StopEvent(Protocol):
    def wait(self, timeout: float) -> bool: ...


def countdown_level(now: float, deadline: float, page_seconds: float) -> int:
    remaining = max(0.0, deadline - now)
    if remaining == 0:
        return 0
    return max(
        0,
        min(
            COUNTDOWN_STEPS,
            math.ceil(COUNTDOWN_STEPS * remaining / page_seconds),
        ),
    )


class DisplayApplication:
    def __init__(
        self,
        *,
        config: DisplayConfig,
        display: DisplayDevice,
        renderer: DisplayRenderer,
        system_provider: SystemStatusProvider,
        network_provider: NetworkStatusProvider,
        cloudflare_provider: CloudflareStatusProvider,
        service_provider: ServiceStatusProvider,
        stop_event: StopEvent,
        clock: Callable[[], float] = time.monotonic,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.display = display
        self.renderer = renderer
        self.system_provider = system_provider
        self.network_provider = network_provider
        self.cloudflare_provider = cloudflare_provider
        self.service_provider = service_provider
        self.stop_event = stop_event
        self.clock = clock
        self.logger = logger or logging.getLogger(__name__)

        self.system = SystemSnapshot.initial()
        self.network = NetworkSnapshot.initial()
        self.service = ServiceSnapshot.initial()

        self.active_page_index = 0
        self.page_deadline = 0.0
        self.next_cpu_refresh = 0.0
        self.next_system_refresh = 0.0
        self.next_storage_refresh = 0.0
        self.next_network_refresh = 0.0
        self.next_tunnel_refresh = 0.0
        self.next_public_refresh = 0.0
        self.next_service_refresh = 0.0

        self._started = False
        self._last_render_key: tuple[object, int] | None = None
        self._observed_values: dict[str, StatusValue] = {}
        self._health_states: dict[str, str] = {}

    def run(self) -> None:
        try:
            self.start(self.clock())
            while not self.stop_event.wait(SCHEDULER_TICK_SECONDS):
                self.tick(self.clock())
        finally:
            self.logger.info("OLED status display shutting down")
            try:
                self.display.cleanup()
            except Exception:
                self.logger.exception("OLED cleanup failed")

    def start(self, now: float) -> None:
        if self._started:
            raise RuntimeError("display application is already started")
        self._started = True
        self.active_page_index = 0
        self.page_deadline = now + self.config.page_seconds
        self._refresh(now, force=True)
        self._render(now, force=True)

    def tick(self, now: float) -> None:
        if not self._started:
            raise RuntimeError("display application has not been started")

        self._refresh(now)
        if now >= self.page_deadline:
            elapsed_pages = (
                int((now - self.page_deadline) // self.config.page_seconds) + 1
            )
            self.active_page_index = (
                self.active_page_index + elapsed_pages
            ) % 3
            self.page_deadline += elapsed_pages * self.config.page_seconds
        self._render(now)

    def _refresh(self, now: float, *, force: bool = False) -> None:
        if force or now >= self.next_cpu_refresh:
            cpu = self._safe_value("CPU", self.system_provider.read_cpu)
            self._observe("CPU", cpu)
            self.system = replace(self.system, cpu=cpu)
            self.next_cpu_refresh = self._next_deadline(
                self.next_cpu_refresh,
                CPU_REFRESH_SECONDS,
                now,
                force=force,
            )

        if force or now >= self.next_system_refresh:
            memory = self._safe_value("Memory", self.system_provider.read_memory)
            uptime = self._safe_value("System uptime", self.system_provider.read_uptime)
            self._observe("Memory", memory)
            self._observe("System uptime", uptime)
            self.system = replace(self.system, memory=memory, uptime=uptime)
            self.next_system_refresh = self._next_deadline(
                self.next_system_refresh,
                SYSTEM_REFRESH_SECONDS,
                now,
                force=force,
            )

        if force or now >= self.next_storage_refresh:
            storage = self._safe_value(
                "Storage",
                self.system_provider.read_storage,
            )
            self._observe("Storage", storage)
            self.system = replace(self.system, storage=storage)
            self.next_storage_refresh = self._next_deadline(
                self.next_storage_refresh,
                STORAGE_REFRESH_SECONDS,
                now,
                force=force,
            )

        if force or now >= self.next_network_refresh:
            wifi = self._safe_value("WiFi", self.network_provider.read_wifi)
            lan = self._safe_value("LAN", self.network_provider.read_lan)

            self._observe("WiFi", wifi)
            self._observe("LAN", lan)
            self._observe_health("WiFi", self._wifi_health(wifi))
            self.network = replace(
                self.network,
                wifi=wifi,
                lan=lan,
            )
            self.next_network_refresh = self._next_deadline(
                self.next_network_refresh,
                NETWORK_REFRESH_SECONDS,
                now,
                force=force,
            )

        if force or now >= self.next_tunnel_refresh:
            tunnel = self._safe_value(
                "Cloudflare tunnel",
                self.cloudflare_provider.read_tunnel,
            )
            self._observe("Cloudflare tunnel", tunnel)
            self._observe_health("Cloudflare tunnel", self._known_text(tunnel))
            self.network = replace(self.network, tunnel=tunnel)
            self.next_tunnel_refresh = self._next_deadline(
                self.next_tunnel_refresh,
                TUNNEL_REFRESH_SECONDS,
                now,
                force=force,
            )

        if force or now >= self.next_public_refresh:
            public = self._safe_value(
                "Public endpoint",
                self.cloudflare_provider.read_public,
            )
            self._observe("Public endpoint", public)
            self._observe_health("Public endpoint", self._known_text(public))
            self.network = replace(self.network, public=public)
            self.next_public_refresh = self._next_deadline(
                self.next_public_refresh,
                PUBLIC_REFRESH_SECONDS,
                now,
                force=force,
            )

        if force or now >= self.next_service_refresh:
            try:
                service = self.service_provider.read_status()
                if not isinstance(service, ServiceSnapshot):
                    raise TypeError("provider returned an invalid service snapshot")
            except Exception as exc:
                unknown = StatusValue.unknown(self._exception_reason(exc))
                service = ServiceSnapshot(
                    state=unknown,
                    process=unknown,
                    uptime=unknown,
                    restarts=unknown,
                )

            self._observe("Webserver state", service.state)
            self._observe("Webserver process", service.process)
            self._observe("Webserver uptime", service.uptime)
            self._observe("Webserver restarts", service.restarts)
            self._observe_health("Webserver", self._known_text(service.state))
            self.service = service
            self.next_service_refresh = self._next_deadline(
                self.next_service_refresh,
                SERVICE_REFRESH_SECONDS,
                now,
                force=force,
            )

    def _render(self, now: float, *, force: bool = False) -> None:
        pages = build_pages(self.network, self.system, self.service)
        page = pages[self.active_page_index]
        level = countdown_level(now, self.page_deadline, self.config.page_seconds)
        render_key = (page, level)
        if not force and render_key == self._last_render_key:
            return

        image = self.renderer.render(page, level)
        self.display.display(image)
        self._last_render_key = render_key

    def _observe(self, name: str, value: StatusValue) -> None:
        previous = self._observed_values.get(name)
        if value.state is ValueState.UNKNOWN:
            if (
                previous is None
                or previous.state is not ValueState.UNKNOWN
                or previous.error != value.error
            ):
                self.logger.warning(
                    "%s is %s: %s",
                    name,
                    UNKNOWN_TEXT,
                    value.error or "unknown error",
                )
        elif previous is not None and previous.state is ValueState.UNKNOWN:
            self.logger.info("%s recovered: %s", name, value.text)
        self._observed_values[name] = value

    def _observe_health(self, name: str, state: str | None) -> None:
        if state is None:
            return
        previous = self._health_states.get(name)
        if previous != state:
            self.logger.info("%s state: %s", name, state)
            self._health_states[name] = state

    @staticmethod
    def _wifi_health(value: StatusValue) -> str | None:
        if value.state is not ValueState.KNOWN:
            return None
        return "down" if value.text == "down" else "connected"

    @staticmethod
    def _known_text(value: StatusValue) -> str | None:
        if value.state is not ValueState.KNOWN:
            return None
        return value.text

    @staticmethod
    def _safe_value(name: str, reader: Callable[[], StatusValue]) -> StatusValue:
        try:
            value = reader()
            if not isinstance(value, StatusValue):
                raise TypeError(f"{name} provider returned an invalid value")
            return value
        except Exception as exc:
            return StatusValue.unknown(DisplayApplication._exception_reason(exc))

    @staticmethod
    def _exception_reason(exc: Exception) -> str:
        message = str(exc).strip()
        return f"{type(exc).__name__}: {message}" if message else type(exc).__name__

    @staticmethod
    def _next_deadline(
        current: float,
        interval: float,
        now: float,
        *,
        force: bool,
    ) -> float:
        if force or current == 0:
            return now + interval
        elapsed_intervals = int((now - current) // interval) + 1
        return current + elapsed_intervals * interval


def main() -> None:
    from door_display.providers.cloudflare import CloudflareProvider
    from door_display.providers.network import NetworkProvider
    from door_display.providers.service import ServiceProvider
    from door_display.providers.system import SystemProvider

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logger = logging.getLogger("oled-display")
    config = load_config(logger=logger)
    logger.info(
        "OLED status display starting with page interval %.3g seconds",
        config.page_seconds,
    )

    stop_requested = Event()

    def request_stop(_signum: int, _frame: FrameType | None) -> None:
        stop_requested.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    try:
        display = create_device()
    except Exception:
        logger.exception("OLED initialization failed")
        raise

    logger.info("OLED initialized on I2C bus 1 at address 0x3c")

    application = DisplayApplication(
        config=config,
        display=display,
        renderer=DisplayRenderer(width=display.width, height=display.height),
        system_provider=SystemProvider(),
        network_provider=NetworkProvider(),
        cloudflare_provider=CloudflareProvider(
            ready_url=config.tunnel_ready_url,
            public_url=config.public_health_url,
        ),
        service_provider=ServiceProvider(),
        stop_event=stop_requested,
    )
    application.run()
