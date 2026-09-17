from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Sequence

if TYPE_CHECKING:
    from PIL.Image import Image


SSD1306_COLUMN_ADDRESS = 0x21
SSD1306_PAGE_ADDRESS = 0x22


class DisplayDevice(Protocol):
    width: int
    height: int

    def display(self, image: Image) -> None: ...

    def cleanup(self) -> None: ...


class RawSSD1306(Protocol):
    width: int
    height: int

    def display(self, image: Image) -> None: ...

    def command(self, *commands: int) -> None: ...

    def data(self, data: Sequence[int]) -> None: ...

    def cleanup(self) -> None: ...


class SSD1306Display:
    """SSD1306 adapter that sends only pages containing changed pixels."""

    def __init__(self, device: RawSSD1306) -> None:
        self._device = device
        self.width = device.width
        self.height = device.height
        self._previous: Image | None = None

    def display(self, image: Image) -> None:
        from PIL import ImageChops

        if image.mode != "1" or image.size != (self.width, self.height):
            raise ValueError("display image must be a 1-bit image matching the device")

        if self._previous is None:
            self._device.display(image)
            self._previous = image.copy()
            return

        bounds = ImageChops.difference(self._previous, image).getbbox()
        if bounds is None:
            return

        left, top, right, bottom = bounds
        first_page = top // 8
        last_page = (bottom - 1) // 8
        self._device.command(
            SSD1306_COLUMN_ADDRESS,
            left,
            right - 1,
            SSD1306_PAGE_ADDRESS,
            first_page,
            last_page,
        )

        pixels = image.load()
        data = bytearray()
        for page in range(first_page, last_page + 1):
            first_row = page * 8
            for x in range(left, right):
                value = 0
                for bit in range(8):
                    if pixels[x, first_row + bit]:
                        value |= 1 << bit
                data.append(value)
        self._device.data(data)
        self._previous = image.copy()

    def cleanup(self) -> None:
        self._device.cleanup()


def create_device() -> DisplayDevice:
    from luma.core.interface.serial import i2c
    from luma.oled.device import ssd1306

    serial = i2c(port=1, address=0x3C)
    device = ssd1306(serial, width=128, height=64)
    return SSD1306Display(device)
