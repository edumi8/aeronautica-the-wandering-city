"""Shared run context threaded through every suite."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import paths
from .workdir import WorkdirManager


@dataclass
class RunContext:
    output_dir: Path = paths.DEFAULT_OUTPUT_DIR
    cache_dir: Path = paths.DEFAULT_CACHE_DIR
    allow_missing_runtime: bool = False
    keep_workdir: bool = False
    skip_build: bool = False
    workdir: WorkdirManager = field(default_factory=lambda: WorkdirManager(keep=False))
    timeouts: dict[str, float] = field(default_factory=dict)

    def timeout(self, phase: str, default: float) -> float:
        return self.timeouts.get(phase, default)

    def evidence_dir(self, *parts: str) -> Path:
        path = self.output_dir.joinpath("evidence", *parts)
        path.mkdir(parents=True, exist_ok=True)
        return path
