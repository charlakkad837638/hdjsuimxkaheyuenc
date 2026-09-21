from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Protocol
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from door_display.models import StatusValue


HTTP_TIMEOUT_SECONDS = 2.0
MAX_RESPONSE_BYTES = 64 * 1024


@dataclass(frozen=True)
class HttpResult:
    status: int
    body: bytes


class HttpGetter(Protocol):
    def __call__(self, url: str, *, timeout: float) -> HttpResult: ...


def get_http(url: str, *, timeout: float) -> HttpResult:
    request = Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json,text/html;q=0.9",
            "User-Agent": "door-oled-health/1",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return HttpResult(
                status=response.status,
                body=response.read(MAX_RESPONSE_BYTES + 1),
            )
    except HTTPError as exc:
        return HttpResult(
            status=exc.code,
            body=exc.read(MAX_RESPONSE_BYTES + 1),
        )


class CloudflareProvider:
    def __init__(
        self,
        *,
        ready_url: str,
        public_url: str | None,
        getter: HttpGetter = get_http,
    ) -> None:
        self.ready_url = ready_url
        self.public_url = public_url
        self.getter = getter

    def read_tunnel(self) -> StatusValue:
        try:
            result = self.getter(
                self.ready_url,
                timeout=HTTP_TIMEOUT_SECONDS,
            )
            if result.status != 200:
                return StatusValue.known("down")
            if len(result.body) > MAX_RESPONSE_BYTES:
                raise ValueError("readiness response is too large")

            payload = json.loads(result.body)
            if not isinstance(payload, dict):
                raise ValueError("readiness response is not an object")
            ready_connections = payload["readyConnections"]
            if isinstance(ready_connections, bool) or not isinstance(
                ready_connections,
                int,
            ):
                raise ValueError("readyConnections is not an integer")
            if ready_connections < 0:
                raise ValueError("readyConnections is negative")
            return StatusValue.known(
                "connected" if ready_connections > 0 else "down"
            )
        except OSError:
            return StatusValue.known("down")
        except Exception as exc:
            return StatusValue.unknown(self._reason("tunnel readiness", exc))

    def read_public(self) -> StatusValue:
        if self.public_url is None:
            return StatusValue.unknown(
                "OLED_PUBLIC_HEALTH_URL is not configured"
            )

        try:
            result = self.getter(
                self.public_url,
                timeout=HTTP_TIMEOUT_SECONDS,
            )
            return StatusValue.known(
                "online" if result.status == 200 else "down"
            )
        except OSError:
            return StatusValue.known("down")
        except Exception as exc:
            return StatusValue.unknown(self._reason("public endpoint", exc))

    @staticmethod
    def _reason(source: str, exc: Exception) -> str:
        detail = str(exc).strip()
        suffix = f": {detail}" if detail else ""
        return f"unable to check {source} ({type(exc).__name__}{suffix})"
