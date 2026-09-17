from __future__ import annotations

from dataclasses import dataclass
import logging
import math
import os
from typing import Mapping


DEFAULT_PAGE_SECONDS = 4.0
MIN_PAGE_SECONDS = 1.0
MAX_PAGE_SECONDS = 300.0


@dataclass(frozen=True)
class DisplayConfig:
    page_seconds: float = DEFAULT_PAGE_SECONDS


def load_config(
    environ: Mapping[str, str] | None = None,
    *,
    logger: logging.Logger | None = None,
) -> DisplayConfig:
    values = os.environ if environ is None else environ
    log = logger or logging.getLogger(__name__)
    raw_value = values.get("OLED_PAGE_SECONDS")

    if raw_value is None:
        return DisplayConfig()

    try:
        page_seconds = float(raw_value.strip())
        if (
            not math.isfinite(page_seconds)
            or page_seconds < MIN_PAGE_SECONDS
            or page_seconds > MAX_PAGE_SECONDS
        ):
            raise ValueError
    except ValueError:
        log.warning(
            "Invalid OLED_PAGE_SECONDS=%r; using %.0f seconds",
            raw_value,
            DEFAULT_PAGE_SECONDS,
        )
        return DisplayConfig()

    return DisplayConfig(page_seconds=page_seconds)
