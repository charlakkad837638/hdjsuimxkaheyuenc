from __future__ import annotations

from door_display.models import (
    DisplayPage,
    NetworkSnapshot,
    ServiceSnapshot,
    SystemSnapshot,
)


def build_pages(
    network: NetworkSnapshot,
    system: SystemSnapshot,
    service: ServiceSnapshot,
) -> tuple[DisplayPage, DisplayPage, DisplayPage]:
    return (
        DisplayPage(
            name="NETWORK",
            rows=(
                f"WiFi: {network.wifi.text}",
                f"LAN: {network.lan.text}",
                f"Tailscale: {network.tailscale.text}",
                f"TS IP: {network.tailscale_ip.text}",
            ),
        ),
        DisplayPage(
            name="SYSTEM",
            rows=(
                f"CPU: {system.cpu.text}",
                f"Memory: {system.memory.text}",
                f"Uptime: {system.uptime.text}",
            ),
        ),
        DisplayPage(
            name="WEBSERVER",
            rows=(
                f"State: {service.state.text}",
                f"Process: {service.process.text}",
                f"Uptime: {service.uptime.text}",
                f"Restarts: {service.restarts.text}",
            ),
        ),
    )
