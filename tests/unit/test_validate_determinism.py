"""Unit tests for the reproducible-build primitives added to
scripts/validate.py (fixed archive timestamps/permissions, sorted file
traversal, sha256 sidecar writer, mod-count drift reporting). Only exercises
the pure/offline functions -- network-dependent dependency resolution is
covered by the `artifact` suite, not here.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def validate_module():
    spec = importlib.util.spec_from_file_location("aeronautica_validate_under_test", ROOT / "scripts" / "validate.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_reproducible_date_time_defaults_to_fixed_epoch(validate_module, monkeypatch):
    monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
    assert validate_module._reproducible_date_time() == (2020, 1, 1, 0, 0, 0)


def test_reproducible_date_time_honors_source_date_epoch(validate_module, monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "0")
    assert validate_module._reproducible_date_time()[:1] == (1970,)


def test_write_deterministic_is_byte_identical_across_two_writes(validate_module, tmp_path):
    payload = b'{"hello": "world"}'
    archive_a = tmp_path / "a.zip"
    archive_b = tmp_path / "b.zip"

    with zipfile.ZipFile(archive_a, "w") as zf:
        validate_module._write_deterministic(zf, "modrinth.index.json", payload)
    with zipfile.ZipFile(archive_b, "w") as zf:
        validate_module._write_deterministic(zf, "modrinth.index.json", payload)

    assert archive_a.read_bytes() == archive_b.read_bytes()


def test_write_deterministic_ignores_wall_clock_time(validate_module, tmp_path, monkeypatch):
    import time as time_module

    payload = b"same content"
    archive_a = tmp_path / "a.zip"
    with zipfile.ZipFile(archive_a, "w") as zf:
        validate_module._write_deterministic(zf, "x.txt", payload)

    # Simulate the second build happening at a very different wall-clock time.
    real_gmtime = time_module.gmtime
    monkeypatch.setattr(time_module, "gmtime", lambda *a: real_gmtime(2000000000))
    archive_b = tmp_path / "b.zip"
    with zipfile.ZipFile(archive_b, "w") as zf:
        validate_module._write_deterministic(zf, "x.txt", payload)

    assert archive_a.read_bytes() == archive_b.read_bytes()


def test_iter_sorted_files_is_order_independent_of_os_walk(validate_module, tmp_path):
    base = tmp_path / "overrides"
    (base / "z_dir").mkdir(parents=True)
    (base / "a_dir").mkdir(parents=True)
    (base / "z_dir" / "z.txt").write_text("z", encoding="utf-8")
    (base / "a_dir" / "a.txt").write_text("a", encoding="utf-8")
    (base / "root.txt").write_text("root", encoding="utf-8")

    files = list(validate_module._iter_sorted_files(base))
    relative = [f.relative_to(base).as_posix() for f in files]
    assert relative == sorted(relative)


def test_write_sha256_sums_output_is_sorted_and_correct(validate_module, tmp_path):
    import hashlib

    file_b = tmp_path / "b-artifact.mrpack"
    file_a = tmp_path / "a-artifact.mrpack"
    file_b.write_bytes(b"second")
    file_a.write_bytes(b"first")

    sums_path = validate_module.write_sha256_sums([file_b, file_a], output_dir=tmp_path)
    lines = sums_path.read_text(encoding="utf-8").splitlines()

    assert lines[0].endswith("a-artifact.mrpack")
    assert lines[1].endswith("b-artifact.mrpack")
    assert lines[0].split()[0] == hashlib.sha256(b"first").hexdigest()


def test_report_resolved_count_drift_prints_note_on_change(validate_module, tmp_path, monkeypatch, capsys):
    index_path = tmp_path / "modrinth.index.json"
    index_path.write_text(json.dumps({"files": [{}] * 38}), encoding="utf-8")
    monkeypatch.setattr(validate_module, "INDEX_PATH", index_path)

    validate_module._report_resolved_count_drift(39)
    captured = capsys.readouterr()
    assert "changed from 38 to 39" in captured.err


def test_report_resolved_count_drift_silent_when_unchanged(validate_module, tmp_path, monkeypatch, capsys):
    index_path = tmp_path / "modrinth.index.json"
    index_path.write_text(json.dumps({"files": [{}] * 38}), encoding="utf-8")
    monkeypatch.setattr(validate_module, "INDEX_PATH", index_path)

    validate_module._report_resolved_count_drift(38)
    captured = capsys.readouterr()
    assert captured.err == ""


def test_no_hardcoded_mod_count_constant(validate_module):
    # Repository invariant: "Never hard-code the number of mods."
    assert not hasattr(validate_module, "EXPECTED_MOD_COUNT")
