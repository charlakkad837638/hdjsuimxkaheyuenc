from __future__ import annotations

from typing import Any, Sequence

from door_display.device import (
    SSD1306_COLUMN_ADDRESS,
    SSD1306_PAGE_ADDRESS,
    SSD1306Display,
)
from door_display.models import DisplayPage
from door_display.renderer import DisplayRenderer


class FakeRawDisplay:
    width = 128
    height = 64

    def __init__(self) -> None:
        self.full_frames: list[Any] = []
        self.commands: list[tuple[int, ...]] = []
        self.data_blocks: list[bytes] = []
        self.cleaned = False

    def display(self, image: Any) -> None:
        self.full_frames.append(image.copy())

    def command(self, *commands: int) -> None:
        self.commands.append(commands)

    def data(self, data: Sequence[int]) -> None:
        self.data_blocks.append(bytes(data))

    def cleanup(self) -> None:
        self.cleaned = True


def test_device_sends_only_changed_bottom_page_after_first_frame() -> None:
    raw = FakeRawDisplay()
    display = SSD1306Display(raw)
    renderer = DisplayRenderer()
    page = DisplayPage(name="SYSTEM", rows=("CPU: 18%",))

    display.display(renderer.render(page, 8))
    display.display(renderer.render(page, 7))

    assert len(raw.full_frames) == 1
    assert raw.commands == [
        (
            SSD1306_COLUMN_ADDRESS,
            112,
            127,
            SSD1306_PAGE_ADDRESS,
            7,
            7,
        )
    ]
    assert raw.data_blocks == [bytes(16)]


def test_device_skips_identical_frame_and_delegates_cleanup() -> None:
    raw = FakeRawDisplay()
    display = SSD1306Display(raw)
    image = DisplayRenderer().render(DisplayPage(name="SYSTEM", rows=()), 8)

    display.display(image)
    display.display(image.copy())
    display.cleanup()

    assert len(raw.full_frames) == 1
    assert raw.commands == []
    assert raw.cleaned is True
