from __future__ import annotations

from collections.abc import Callable
import math
from pathlib import Path
from shutil import disk_usage

from door_display.models import StatusValue, format_duration
from door_display.providers.common import TextReader, read_text


PROC_STAT = Path("/proc/stat")
PROC_MEMINFO = Path("/proc/meminfo")
PROC_UPTIME = Path("/proc/uptime")
STORAGE_ROOT = Path("/")
GIBIBYTE = 1024**3

DiskUsageReader = Callable[[Path], tuple[int, int, int]]


class SystemProvider:
    def __init__(
        self,
        *,
        reader: TextReader = read_text,
        disk_usage_reader: DiskUsageReader = disk_usage,
    ) -> None:
        self.reader = reader
        self.disk_usage_reader = disk_usage_reader
        self._previous_cpu: tuple[int, int] | None = None

    def read_cpu(self) -> StatusValue:
        try:
            first_line = self.reader(PROC_STAT).splitlines()[0]
            parts = first_line.split()
            if not parts or parts[0] != "cpu" or len(parts) < 5:
                raise ValueError("aggregate cpu row is missing required fields")

            counters = tuple(int(value) for value in parts[1:9])
            if len(counters) < 4 or any(value < 0 for value in counters):
                raise ValueError("aggregate cpu counters are invalid")

            idle = counters[3] + (counters[4] if len(counters) > 4 else 0)
            total = sum(counters)
            current = (total, idle)
            previous = self._previous_cpu
            self._previous_cpu = current

            if previous is None:
                return StatusValue.measuring()

            total_delta = total - previous[0]
            idle_delta = idle - previous[1]
            if total_delta <= 0 or idle_delta < 0 or idle_delta > total_delta:
                raise ValueError("aggregate cpu counters did not advance normally")

            percent = 100.0 * (total_delta - idle_delta) / total_delta
            return self._percent_value(percent, "cpu percentage")
        except Exception as exc:
            return StatusValue.unknown(self._reason("/proc/stat", exc))

    def read_memory(self) -> StatusValue:
        try:
            values: dict[str, int] = {}
            for line in self.reader(PROC_MEMINFO).splitlines():
                key, separator, remainder = line.partition(":")
                if not separator:
                    continue
                fields = remainder.split()
                if fields:
                    values[key] = int(fields[0])

            total = values["MemTotal"]
            available = values["MemAvailable"]
            if total <= 0 or available < 0 or available > total:
                raise ValueError("memory counters are internally inconsistent")

            percent = 100.0 * (total - available) / total
            return self._percent_value(percent, "memory percentage")
        except Exception as exc:
            return StatusValue.unknown(self._reason("/proc/meminfo", exc))

    def read_uptime(self) -> StatusValue:
        try:
            first_field = self.reader(PROC_UPTIME).split()[0]
            seconds = float(first_field)
            return StatusValue.known(format_duration(seconds))
        except Exception as exc:
            return StatusValue.unknown(self._reason("/proc/uptime", exc))

    def read_storage(self) -> StatusValue:
        try:
            total, used, free = self.disk_usage_reader(STORAGE_ROOT)
            counters = (total, used, free)
            if any(
                isinstance(value, bool) or not isinstance(value, int)
                for value in counters
            ):
                raise ValueError("storage counters must be integers")
            if (
                total <= 0
                or used < 0
                or free < 0
                or used > total
                or free > total
                or used + free > total
            ):
                raise ValueError("storage counters are internally inconsistent")
            return StatusValue.known(
                f"{used / GIBIBYTE:.1f}G used / "
                f"{free / GIBIBYTE:.1f}G free"
            )
        except Exception as exc:
            return StatusValue.unknown(self._reason("storage for /", exc))

    @staticmethod
    def _percent_value(percent: float, name: str) -> StatusValue:
        if not math.isfinite(percent) or percent < 0 or percent > 100:
            raise ValueError(f"{name} is outside 0-100")
        return StatusValue.known(f"{round(percent)}%")

    @staticmethod
    def _reason(source: str, exc: Exception) -> str:
        detail = str(exc).strip()
        suffix = f": {detail}" if detail else ""
        return f"unable to parse {source} ({type(exc).__name__}{suffix})"
