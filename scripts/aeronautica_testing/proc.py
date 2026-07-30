"""Subprocess execution with timeouts, timing, and captured evidence logs.

Every external command the pipeline runs (docker, java, gradle, the
installer, ...) should go through :func:`run` so that timeout handling,
duration measurement, and log capture behave identically everywhere.
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CommandResult:
    command: list[str]
    returncode: int | None
    duration_seconds: float
    timed_out: bool
    stdout_path: Path | None
    stdout_tail: str


def _tail(text: str, max_lines: int = 60) -> str:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    return "\n".join(["... (truncated, see evidence log) ..."] + lines[-max_lines:])


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    timeout_seconds: float = 600,
    env: dict[str, str] | None = None,
    log_path: Path | None = None,
    input_text: str | None = None,
) -> CommandResult:
    """Run ``command``, merging stdout+stderr, always returning a
    CommandResult instead of raising on non-zero exit or timeout so callers
    can turn either into a structured Result.
    """
    started = time.monotonic()
    timed_out = False
    output = ""
    returncode: int | None = None
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            env=env,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            encoding="utf-8",
            errors="replace",
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        returncode = completed.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = exc.stdout or b"" if isinstance(exc.stdout, (bytes, bytearray)) else (exc.stdout or "")
        stderr = exc.stderr or b"" if isinstance(exc.stderr, (bytes, bytearray)) else (exc.stderr or "")
        if isinstance(stdout, (bytes, bytearray)):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, (bytes, bytearray)):
            stderr = stderr.decode("utf-8", errors="replace")
        output = stdout + stderr
    except FileNotFoundError as exc:
        output = f"executable not found: {exc}"
        returncode = 127
    duration = time.monotonic() - started

    stdout_path = None
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        header = f"$ {' '.join(command)}\n(cwd={cwd})\n\n"
        log_path.write_text(header + output, encoding="utf-8", errors="replace")
        stdout_path = log_path

    return CommandResult(
        command=command,
        returncode=returncode,
        duration_seconds=duration,
        timed_out=timed_out,
        stdout_path=stdout_path,
        stdout_tail=_tail(output),
    )
