"""Shared pytest fixtures: puts scripts/ on sys.path so `aeronautica_testing`
imports the same way it does when scripts/test_pipeline.py runs it, and
provides small builders for constructing throwaway .mrpack zip fixtures
in-memory (see "malicious/invalid test fixtures" in TESTING.md).
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402


def valid_index(**overrides: Any) -> dict[str, Any]:
    base = {
        "game": "minecraft",
        "formatVersion": 1,
        "versionId": "0.1.0-test",
        "name": "Aeronautica Test Fixture",
        "summary": "unit test fixture",
        "files": [],
        "dependencies": {"minecraft": "1.20.1", "forge": "47.4.10"},
    }
    base.update(overrides)
    return base


def valid_file_entry(**overrides: Any) -> dict[str, Any]:
    entry = {
        "path": "mods/test-mod.jar",
        "hashes": {"sha1": "a" * 40, "sha512": "b" * 128},
        "env": {"client": "required", "server": "required"},
        "downloads": ["https://cdn.modrinth.com/data/AAAAAAAA/versions/BBBBBBBB/test-mod.jar"],
        "fileSize": 12345,
    }
    entry.update(overrides)
    return entry


def write_mrpack(
    path: Path,
    *,
    index: dict[str, Any] | None | list = "__default__",
    raw_index_entries: list[tuple[str, bytes]] | None = None,
    extra_entries: dict[str, bytes] | None = None,
) -> Path:
    """Build a minimal .mrpack-shaped zip. Pass `index=None` to omit
    modrinth.index.json entirely, or `raw_index_entries` to control the
    exact zip member(s) written for it (e.g. duplicate entries, invalid
    UTF-8, non-JSON content).
    """
    if index == "__default__":
        index = valid_index()

    with zipfile.ZipFile(path, "w") as zf:
        if raw_index_entries is not None:
            for name, data in raw_index_entries:
                zf.writestr(name, data)
        elif index is not None:
            zf.writestr("modrinth.index.json", json.dumps(index).encode("utf-8"))
        zf.writestr("icon.png", b"\x89PNG\r\n\x1a\n")
        if extra_entries:
            for name, data in extra_entries.items():
                zf.writestr(name, data)
    return path


@pytest.fixture
def mrpack_factory(tmp_path):
    counter = {"n": 0}

    def _make(**kwargs) -> Path:
        counter["n"] += 1
        return write_mrpack(tmp_path / f"fixture-{counter['n']}.mrpack", **kwargs)

    return _make
