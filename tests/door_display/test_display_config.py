from __future__ import annotations

import logging

import pytest

from door_display.config import (
    DEFAULT_PAGE_SECONDS,
    DEFAULT_TUNNEL_READY_URL,
    load_config,
)


def test_page_seconds_defaults_when_absent() -> None:
    config = load_config({})

    assert config.page_seconds == DEFAULT_PAGE_SECONDS
    assert config.tunnel_ready_url == DEFAULT_TUNNEL_READY_URL
    assert config.public_health_url is None


def test_page_seconds_accepts_finite_value_in_range() -> None:
    assert load_config({"OLED_PAGE_SECONDS": " 6.5 "}).page_seconds == 6.5


@pytest.mark.parametrize(
    "value",
    ["", "not-a-number", "nan", "inf", "0.5", "301"],
)
def test_invalid_page_seconds_warns_and_uses_default(
    value: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        config = load_config({"OLED_PAGE_SECONDS": value})

    assert config.page_seconds == DEFAULT_PAGE_SECONDS
    assert len(caplog.records) == 1
    assert "Invalid OLED_PAGE_SECONDS" in caplog.text


def test_health_urls_accept_loopback_http_and_public_https() -> None:
    config = load_config(
        {
            "OLED_TUNNEL_READY_URL": "http://localhost:60123/ready",
            "OLED_PUBLIC_HEALTH_URL": "https://door.example.com/door",
        }
    )

    assert config.tunnel_ready_url == "http://localhost:60123/ready"
    assert config.public_health_url == "https://door.example.com/door"


@pytest.mark.parametrize(
    ("name", "value", "expected"),
    [
        (
            "OLED_TUNNEL_READY_URL",
            "http://192.168.1.2:60123/ready",
            DEFAULT_TUNNEL_READY_URL,
        ),
        (
            "OLED_PUBLIC_HEALTH_URL",
            "http://door.example.com/door",
            None,
        ),
    ],
)
def test_invalid_health_url_warns_and_uses_default(
    name: str,
    value: str,
    expected: str | None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        config = load_config({name: value})

    attribute = (
        "tunnel_ready_url"
        if name == "OLED_TUNNEL_READY_URL"
        else "public_health_url"
    )
    assert getattr(config, attribute) == expected
    assert f"Invalid {name}" in caplog.text
