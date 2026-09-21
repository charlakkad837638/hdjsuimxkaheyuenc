from __future__ import annotations

from dataclasses import dataclass
import logging
import math
import os
from typing import Mapping
from urllib.parse import urlsplit


DEFAULT_PAGE_SECONDS = 4.0
MIN_PAGE_SECONDS = 1.0
MAX_PAGE_SECONDS = 300.0
DEFAULT_TUNNEL_READY_URL = "http://127.0.0.1:60123/ready"


@dataclass(frozen=True)
class DisplayConfig:
    page_seconds: float = DEFAULT_PAGE_SECONDS
    tunnel_ready_url: str = DEFAULT_TUNNEL_READY_URL
    public_health_url: str | None = None


def load_config(
    environ: Mapping[str, str] | None = None,
    *,
    logger: logging.Logger | None = None,
) -> DisplayConfig:
    values = os.environ if environ is None else environ
    log = logger or logging.getLogger(__name__)
    return DisplayConfig(
        page_seconds=_page_seconds(values.get("OLED_PAGE_SECONDS"), log),
        tunnel_ready_url=_url(
            name="OLED_TUNNEL_READY_URL",
            raw_value=values.get("OLED_TUNNEL_READY_URL"),
            default=DEFAULT_TUNNEL_READY_URL,
            schemes={"http"},
            loopback_only=True,
            logger=log,
        ),
        public_health_url=_url(
            name="OLED_PUBLIC_HEALTH_URL",
            raw_value=values.get("OLED_PUBLIC_HEALTH_URL"),
            default=None,
            schemes={"https"},
            loopback_only=False,
            logger=log,
        ),
    )


def _page_seconds(raw_value: str | None, logger: logging.Logger) -> float:
    if raw_value is None:
        return DEFAULT_PAGE_SECONDS

    try:
        page_seconds = float(raw_value.strip())
        if (
            not math.isfinite(page_seconds)
            or page_seconds < MIN_PAGE_SECONDS
            or page_seconds > MAX_PAGE_SECONDS
        ):
            raise ValueError
    except ValueError:
        logger.warning(
            "Invalid OLED_PAGE_SECONDS=%r; using %.0f seconds",
            raw_value,
            DEFAULT_PAGE_SECONDS,
        )
        return DEFAULT_PAGE_SECONDS
    return page_seconds


def _url(
    *,
    name: str,
    raw_value: str | None,
    default: str | None,
    schemes: set[str],
    loopback_only: bool,
    logger: logging.Logger,
) -> str | None:
    if raw_value is None:
        return default

    value = raw_value.strip()
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in schemes
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError
        if loopback_only and parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError
    except ValueError:
        logger.warning("Invalid %s=%r; using %r", name, raw_value, default)
        return default
    return value
