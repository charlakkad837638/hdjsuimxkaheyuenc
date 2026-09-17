from __future__ import annotations

import logging

import pytest

from door_display.config import DEFAULT_PAGE_SECONDS, load_config


def test_page_seconds_defaults_when_absent() -> None:
    assert load_config({}).page_seconds == DEFAULT_PAGE_SECONDS


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
