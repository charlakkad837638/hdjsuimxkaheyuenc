from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math


UNKNOWN_TEXT = "[UNKOWN]"
MEASURING_TEXT = "measuring..."


class ValueState(str, Enum):
    KNOWN = "known"
    MEASURING = "measuring"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class StatusValue:
    text: str
    state: ValueState = ValueState.KNOWN
    error: str | None = None

    @classmethod
    def known(cls, text: str) -> StatusValue:
        return cls(text=text)

    @classmethod
    def measuring(cls) -> StatusValue:
        return cls(text=MEASURING_TEXT, state=ValueState.MEASURING)

    @classmethod
    def unknown(cls, error: str) -> StatusValue:
        return cls(text=UNKNOWN_TEXT, state=ValueState.UNKNOWN, error=error)


@dataclass(frozen=True)
class SystemSnapshot:
    cpu: StatusValue
    memory: StatusValue
    uptime: StatusValue

    @classmethod
    def initial(cls) -> SystemSnapshot:
        not_collected = StatusValue.unknown("not collected")
        return cls(
            cpu=StatusValue.measuring(),
            memory=not_collected,
            uptime=not_collected,
        )


@dataclass(frozen=True)
class NetworkSnapshot:
    wifi: StatusValue
    lan: StatusValue
    tailscale: StatusValue
    tailscale_ip: StatusValue

    @classmethod
    def initial(cls) -> NetworkSnapshot:
        not_collected = StatusValue.unknown("not collected")
        return cls(
            wifi=not_collected,
            lan=not_collected,
            tailscale=not_collected,
            tailscale_ip=not_collected,
        )


@dataclass(frozen=True)
class ServiceSnapshot:
    state: StatusValue
    process: StatusValue
    uptime: StatusValue
    restarts: StatusValue

    @classmethod
    def initial(cls) -> ServiceSnapshot:
        not_collected = StatusValue.unknown("not collected")
        return cls(
            state=not_collected,
            process=not_collected,
            uptime=not_collected,
            restarts=not_collected,
        )


@dataclass(frozen=True)
class DisplayPage:
    name: str
    rows: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.name or self.name != self.name.upper():
            raise ValueError("page name must be non-empty uppercase text")
        if len(self.rows) > 4:
            raise ValueError("a display page can contain at most four status rows")

    @property
    def header(self) -> str:
        return f"~~{self.name}~~"

    @property
    def lines(self) -> tuple[str, ...]:
        return (self.header, *self.rows)


def format_duration(seconds: float) -> str:
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("duration must be finite and non-negative")

    total_minutes = int(seconds // 60)
    days, remaining_minutes = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(remaining_minutes, 60)

    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"
