from __future__ import annotations

from PIL import Image, ImageDraw

from door_display.models import (
    DisplayPage,
    NetworkSnapshot,
    ServiceSnapshot,
    StatusValue,
    SystemSnapshot,
    UNKNOWN_TEXT,
)
from door_display.pages import build_pages
from door_display.renderer import DisplayRenderer


def known(text: str) -> StatusValue:
    return StatusValue.known(text)


def test_pages_have_exact_headers_rows_and_order() -> None:
    pages = build_pages(
        NetworkSnapshot(
            wifi=known("-57 dBm"),
            lan=known("192.168.178.33"),
            tunnel=known("connected"),
            public=known("online"),
        ),
        SystemSnapshot(
            cpu=known("18%"),
            memory=known("43%"),
            uptime=known("3d 6h"),
        ),
        ServiceSnapshot(
            state=known("active"),
            process=known("running"),
            uptime=known("2h 14m"),
            restarts=known("0"),
        ),
    )

    assert [page.name for page in pages] == ["NETWORK", "SYSTEM", "WEBSERVER"]
    assert [page.header for page in pages] == [
        "~~NETWORK~~",
        "~~SYSTEM~~",
        "~~WEBSERVER~~",
    ]
    assert pages[0].rows == (
        "WiFi: -57 dBm",
        "LAN: 192.168.178.33",
        "Tunnel: connected",
        "Public: online",
    )
    assert pages[1].rows == ("CPU: 18%", "Memory: 43%", "Uptime: 3d 6h")
    assert pages[2].rows == (
        "State: active",
        "Process: running",
        "Uptime: 2h 14m",
        "Restarts: 0",
    )


def test_unknown_text_is_rendered_as_a_plain_value() -> None:
    page = DisplayPage(name="SYSTEM", rows=(f"CPU: {UNKNOWN_TEXT}",))
    assert page.lines == ("~~SYSTEM~~", "CPU: [UNKOWN]")


def test_renderer_draws_eight_step_countdown_bar() -> None:
    renderer = DisplayRenderer()
    page = DisplayPage(name="SYSTEM", rows=("CPU: 18%",))

    image = renderer.render(page, countdown_level=4)

    assert image.size == (128, 64)
    assert image.getpixel((0, 62)) == 1
    assert image.getpixel((63, 63)) == 1
    assert image.getpixel((64, 62)) == 0
    assert image.getpixel((127, 63)) == 0


def test_renderer_truncates_long_rows_with_ascii_ellipsis() -> None:
    renderer = DisplayRenderer(width=64)
    image = Image.new("1", (64, 64))
    draw = ImageDraw.Draw(image)

    rendered = renderer._truncate(draw, "LAN: 192.168.178.123")

    assert rendered.endswith("...")
    assert renderer._text_width(draw, rendered) <= 64
