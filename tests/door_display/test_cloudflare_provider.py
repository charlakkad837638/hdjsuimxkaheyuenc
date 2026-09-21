from __future__ import annotations

from typing import Callable

import pytest

from door_display.models import UNKNOWN_TEXT, ValueState
from door_display.providers.cloudflare import (
    HTTP_TIMEOUT_SECONDS,
    CloudflareProvider,
    HttpResult,
)


class FakeGetter:
    def __init__(
        self,
        results: dict[str, HttpResult | Exception],
    ) -> None:
        self.results = results
        self.calls: list[tuple[str, float]] = []

    def __call__(self, url: str, *, timeout: float) -> HttpResult:
        self.calls.append((url, timeout))
        result = self.results[url]
        if isinstance(result, Exception):
            raise result
        return result


def make_provider(
    getter: Callable[..., HttpResult],
    *,
    public_url: str | None = "https://door.example.com/door",
) -> CloudflareProvider:
    return CloudflareProvider(
        ready_url="http://127.0.0.1:60123/ready",
        public_url=public_url,
        getter=getter,
    )


@pytest.mark.parametrize(
    ("connections", "expected"),
    [(4, "connected"), (0, "down")],
)
def test_tunnel_health_uses_ready_connections(
    connections: int,
    expected: str,
) -> None:
    getter = FakeGetter(
        {
            "http://127.0.0.1:60123/ready": HttpResult(
                status=200,
                body=(
                    f'{{"status":200,"readyConnections":{connections}}}'
                ).encode(),
            )
        }
    )

    assert make_provider(getter).read_tunnel().text == expected
    assert getter.calls == [
        ("http://127.0.0.1:60123/ready", HTTP_TIMEOUT_SECONDS)
    ]


@pytest.mark.parametrize(
    "result",
    [
        HttpResult(status=503, body=b""),
        HttpResult(status=200, body=b'{"readyConnections":0}'),
    ],
)
def test_tunnel_reports_known_down(result: HttpResult) -> None:
    getter = FakeGetter({"http://127.0.0.1:60123/ready": result})

    value = make_provider(getter).read_tunnel()

    assert value.state is ValueState.KNOWN
    assert value.text == "down"


@pytest.mark.parametrize(
    "result",
    [
        HttpResult(status=200, body=b"not-json"),
        HttpResult(status=200, body=b'{"readyConnections":true}'),
    ],
)
def test_invalid_tunnel_response_is_unknown(
    result: HttpResult | Exception,
) -> None:
    getter = FakeGetter({"http://127.0.0.1:60123/ready": result})

    value = make_provider(getter).read_tunnel()

    assert value.state is ValueState.UNKNOWN
    assert value.text == UNKNOWN_TEXT
    assert value.error


def test_tunnel_transport_failure_is_down() -> None:
    getter = FakeGetter(
        {
            "http://127.0.0.1:60123/ready": TimeoutError("timed out"),
        }
    )

    value = make_provider(getter).read_tunnel()

    assert value.state is ValueState.KNOWN
    assert value.text == "down"


@pytest.mark.parametrize(
    ("status", "expected"),
    [(200, "online"), (403, "down"), (503, "down")],
)
def test_public_health_uses_http_status(status: int, expected: str) -> None:
    getter = FakeGetter(
        {
            "https://door.example.com/door": HttpResult(
                status=status,
                body=b"",
            )
        }
    )

    assert make_provider(getter).read_public().text == expected


def test_public_transport_failure_is_down() -> None:
    getter = FakeGetter(
        {
            "https://door.example.com/door": TimeoutError("timed out"),
        }
    )

    value = make_provider(getter).read_public()

    assert value.state is ValueState.KNOWN
    assert value.text == "down"


def test_public_health_requires_a_configured_url() -> None:
    value = make_provider(FakeGetter({}), public_url=None).read_public()

    assert value.state is ValueState.UNKNOWN
    assert value.text == UNKNOWN_TEXT
    assert value.error == "OLED_PUBLIC_HEALTH_URL is not configured"
