from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Protocol, Sequence


COMMAND_TIMEOUT_SECONDS = 1.0


class TextReader(Protocol):
    def __call__(self, path: Path) -> str: ...


class CommandRunner(Protocol):
    def __call__(
        self,
        args: Sequence[str],
        *,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]: ...


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def run_command(
    args: Sequence[str],
    *,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def command_failure(
    command: str,
    result: subprocess.CompletedProcess[str],
) -> str:
    detail = result.stderr.strip() or result.stdout.strip() or "no error output"
    return f"{command} exited with {result.returncode}: {detail}"
