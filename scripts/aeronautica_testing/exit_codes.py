"""Stable, documented process exit codes for the test pipeline.

These are part of the public contract of ``scripts/test_pipeline.py`` and are
relied on by the Bash/PowerShell wrappers and GitHub Actions workflows.  Do
not renumber existing codes; add new ones instead.
"""
from __future__ import annotations

import enum


class ExitCode(enum.IntEnum):
    OK = 0
    """All executed tests passed (or nothing failed)."""

    TESTS_FAILED = 1
    """At least one test/phase reported status=failed."""

    USAGE_ERROR = 2
    """Bad CLI arguments, unknown suite, or similar user error."""

    PREREQUISITE_MISSING = 3
    """A required prerequisite (Docker, Java 17, Xvfb, ...) was not available
    and ``--allow-missing-runtime`` was not passed."""

    INTERNAL_ERROR = 4
    """An unhandled exception occurred inside the pipeline itself. This code
    must be used for *any* uncaught exception so that a crash can never be
    mistaken for success (exit 0)."""

    INTERRUPTED = 130
    """The run was interrupted by SIGINT/Ctrl-C."""


def worst(codes: list[int]) -> int:
    """Combine several exit codes into the single code the process should
    return. Higher-severity codes win; ``OK`` only if every code is ``OK``.
    """
    if not codes:
        return ExitCode.OK
    if ExitCode.INTERNAL_ERROR in codes:
        return ExitCode.INTERNAL_ERROR
    if ExitCode.INTERRUPTED in codes:
        return ExitCode.INTERRUPTED
    if ExitCode.USAGE_ERROR in codes:
        return ExitCode.USAGE_ERROR
    if ExitCode.PREREQUISITE_MISSING in codes:
        return ExitCode.PREREQUISITE_MISSING
    if ExitCode.TESTS_FAILED in codes:
        return ExitCode.TESTS_FAILED
    return ExitCode.OK
