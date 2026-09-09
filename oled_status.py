from __future__ import annotations

import signal
from threading import Event

from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import ssd1306
from PIL import ImageFont

TEXT = "Hello, world!"
STOP_REQUESTED = Event()


def request_stop(_signum: int, _frame: object) -> None:
    STOP_REQUESTED.set()


def main() -> None:
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    serial = i2c(port=1, address=0x3C)
    display = ssd1306(serial, width=128, height=64)
    font = ImageFont.load_default()

    left, top, right, bottom = font.getbbox(TEXT)
    text_width = right - left
    text_height = bottom - top

    x = display.width
    y = (display.height - text_height) // 2 - top

    print("OLED initialized on I2C bus 1 at address 0x3c", flush=True)

    try:
        while not STOP_REQUESTED.is_set():
            with canvas(display) as draw:
                draw.text((x, y), TEXT, font=font, fill="white")

            x -= 1
            if x < -text_width:
                x = display.width

            STOP_REQUESTED.wait(0.08)
    finally:
        display.cleanup()


if __name__ == "__main__":
    main()
