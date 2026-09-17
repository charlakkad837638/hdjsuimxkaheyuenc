from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

from door_display.models import DisplayPage


TEXT_Y_POSITIONS = (0, 12, 24, 36, 48)
COUNTDOWN_STEPS = 8
COUNTDOWN_HEIGHT = 2


class DisplayRenderer:
    def __init__(
        self,
        *,
        width: int = 128,
        height: int = 64,
        font: ImageFont.ImageFont | None = None,
    ) -> None:
        if width <= 0 or height <= COUNTDOWN_HEIGHT:
            raise ValueError("display dimensions are too small")
        self.width = width
        self.height = height
        self.font = font or ImageFont.load_default()
        self._cached_page: DisplayPage | None = None
        self._cached_base: Image.Image | None = None

    def render(self, page: DisplayPage, countdown_level: int) -> Image.Image:
        if not 0 <= countdown_level <= COUNTDOWN_STEPS:
            raise ValueError("countdown level must be between 0 and 8")

        if page != self._cached_page or self._cached_base is None:
            base = Image.new("1", (self.width, self.height), color=0)
            base_draw = ImageDraw.Draw(base)
            for y, line in zip(TEXT_Y_POSITIONS, page.lines):
                base_draw.text(
                    (0, y),
                    self._truncate(base_draw, line),
                    font=self.font,
                    fill=1,
                )
            self._cached_page = page
            self._cached_base = base

        image = self._cached_base.copy()

        if countdown_level:
            draw = ImageDraw.Draw(image)
            bar_width = round(self.width * countdown_level / COUNTDOWN_STEPS)
            draw.rectangle(
                (
                    0,
                    self.height - COUNTDOWN_HEIGHT,
                    bar_width - 1,
                    self.height - 1,
                ),
                fill=1,
            )

        return image

    def _truncate(self, draw: ImageDraw.ImageDraw, text: str) -> str:
        if self._text_width(draw, text) <= self.width:
            return text

        suffix = "..."
        available = self.width - self._text_width(draw, suffix)
        if available <= 0:
            return ""

        prefix = text
        while prefix and self._text_width(draw, prefix) > available:
            prefix = prefix[:-1]
        return f"{prefix}{suffix}"

    def _text_width(self, draw: ImageDraw.ImageDraw, text: str) -> int:
        left, _top, right, _bottom = draw.textbbox((0, 0), text, font=self.font)
        return right - left
