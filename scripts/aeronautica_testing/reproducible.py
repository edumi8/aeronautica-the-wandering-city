"""Reproducible-build check: build the pack twice into isolated clean
temporary directories and confirm byte-identical SHA-256 output.

Relies on scripts/validate.py's ``--output-dir`` flag and the deterministic
archive writer (fixed timestamp/permissions, sorted traversal) added
alongside this pipeline -- see validate.py's ``_write_deterministic``.
"""
from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

from . import paths
from .proc import run as run_command


@dataclass
class ReproducibleBuildOutcome:
    ok: bool
    message: str
    build_a_dir: Path
    build_b_dir: Path
    compared_files: list[str]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_reproducible_build_check(
    *,
    build_a_dir: Path,
    build_b_dir: Path,
    verify_downloads: bool = False,
    timeout_seconds: float = 600,
    log_dir: Path | None = None,
) -> tuple[ReproducibleBuildOutcome, list]:
    """Returns (outcome, [CommandResult, CommandResult]) for the two builds."""
    command_base = [sys.executable, str(paths.VALIDATE_PY), "--build"]
    if verify_downloads:
        command_base.append("--verify-downloads")

    results = []
    for label, out_dir in (("a", build_a_dir), ("b", build_b_dir)):
        log_path = (log_dir / f"reproducible-build-{label}.log") if log_dir else None
        result = run_command(
            command_base + ["--output-dir", str(out_dir)],
            cwd=paths.ROOT,
            timeout_seconds=timeout_seconds,
            log_path=log_path,
        )
        results.append(result)
        if result.timed_out or result.returncode != 0:
            return (
                ReproducibleBuildOutcome(
                    ok=False,
                    message=f"build {label} failed (returncode={result.returncode}, timed_out={result.timed_out}): "
                    f"{result.stdout_tail}",
                    build_a_dir=build_a_dir,
                    build_b_dir=build_b_dir,
                    compared_files=[],
                ),
                results,
            )

    files_a = {p.name: p for p in build_a_dir.iterdir() if p.is_file()}
    files_b = {p.name: p for p in build_b_dir.iterdir() if p.is_file()}
    if set(files_a) != set(files_b):
        return (
            ReproducibleBuildOutcome(
                ok=False,
                message=f"the two builds produced different file sets: {sorted(files_a)} vs {sorted(files_b)}",
                build_a_dir=build_a_dir,
                build_b_dir=build_b_dir,
                compared_files=[],
            ),
            results,
        )

    mismatches = []
    compared = []
    for name in sorted(files_a):
        hash_a = _sha256(files_a[name])
        hash_b = _sha256(files_b[name])
        compared.append(name)
        if hash_a != hash_b:
            mismatches.append(f"{name}: {hash_a} != {hash_b}")

    if mismatches:
        return (
            ReproducibleBuildOutcome(
                ok=False,
                message="SHA-256 mismatch between the two builds:\n" + "\n".join(mismatches),
                build_a_dir=build_a_dir,
                build_b_dir=build_b_dir,
                compared_files=compared,
            ),
            results,
        )

    return (
        ReproducibleBuildOutcome(
            ok=True,
            message=f"{len(compared)} artefact(s) byte-identical across two independent builds: {compared}",
            build_a_dir=build_a_dir,
            build_b_dir=build_b_dir,
            compared_files=compared,
        ),
        results,
    )
