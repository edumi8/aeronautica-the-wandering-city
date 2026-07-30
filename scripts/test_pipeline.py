#!/usr/bin/env python3
"""Aeronautica: The Wandering City -- unified local/CI test pipeline entry point.

    python scripts/test_pipeline.py <prereqs|fast|artifact|client|server|gametest|worldgen|full> [options]

This file is intentionally a thin shim: all real logic lives in the small,
independently-testable modules under scripts/aeronautica_testing/. See
TESTING.md for the full suite catalogue, or run with --help.
"""
from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info < (3, 11):
    print(f"ERROR: Python 3.11+ is required (found {sys.version.split()[0]}).", file=sys.stderr)
    raise SystemExit(2)

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aeronautica_testing.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
