"""Unit tests for safe temporary-directory handling -- the "never
recursively delete an unresolved or broad path" and "--keep-workdir"
requirements from TESTING.md."""
from __future__ import annotations

from aeronautica_testing.workdir import WorkdirManager


def test_new_creates_an_existing_directory(tmp_path):
    manager = WorkdirManager(keep=False, base_dir=tmp_path / "base")
    created = manager.new("client-gamedir")
    assert created.exists()
    assert created.is_dir()
    assert created.parent == (tmp_path / "base")


def test_cleanup_removes_created_directories_by_default(tmp_path):
    manager = WorkdirManager(keep=False, base_dir=tmp_path / "base")
    created = manager.new("scratch")
    (created / "some-file.txt").write_text("data", encoding="utf-8")

    retained = manager.cleanup()

    assert retained == []
    assert not created.exists()


def test_keep_workdir_retains_directories(tmp_path):
    manager = WorkdirManager(keep=True, base_dir=tmp_path / "base")
    created = manager.new("scratch")

    retained = manager.cleanup()

    assert retained == [created]
    assert created.exists()


def test_cleanup_only_ever_touches_paths_it_created(tmp_path):
    untouched = tmp_path / "unrelated-directory"
    untouched.mkdir()
    (untouched / "important.txt").write_text("do not delete", encoding="utf-8")

    manager = WorkdirManager(keep=False, base_dir=tmp_path / "base")
    manager.new("scratch")
    manager.cleanup()

    assert untouched.exists()
    assert (untouched / "important.txt").read_text(encoding="utf-8") == "do not delete"


def test_multiple_new_calls_produce_distinct_directories(tmp_path):
    manager = WorkdirManager(keep=True, base_dir=tmp_path / "base")
    first = manager.new("client")
    second = manager.new("client")
    assert first != second
    assert first.exists() and second.exists()
