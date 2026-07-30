"""Unit tests for the deep .mrpack structural/security validator, including
the malicious/invalid fixtures required by TESTING.md Phase 3: path
traversal, duplicate paths, case collisions, malformed hashes, incorrect
size, invalid env values, invalid dependencies, override collisions,
absent modrinth.index.json, and multiple modrinth.index.json entries.
"""
from __future__ import annotations

from conftest import valid_file_entry, valid_index

from aeronautica_testing import mrpack_validate as mv


def _categories(issues):
    return {issue.category for issue in issues}


def test_valid_minimal_archive_has_no_issues(mrpack_factory):
    index = valid_index(files=[valid_file_entry()])
    path = mrpack_factory(index=index)
    issues = mv.validate_archive(path, expected_mc="1.20.1", expected_forge="47.4.10")
    assert issues == []


def test_absent_modrinth_index_json(mrpack_factory):
    path = mrpack_factory(index=None)
    issues = mv.validate_archive(path, expected_mc="1.20.1", expected_forge="47.4.10")
    assert any("absent" in i.message for i in issues)


def test_multiple_modrinth_index_json_entries(mrpack_factory):
    path = mrpack_factory(
        raw_index_entries=[
            ("modrinth.index.json", b"{}"),
            ("modrinth.index.json", b"{}"),
        ]
    )
    issues = mv.validate_archive(path, expected_mc="1.20.1", expected_forge="47.4.10")
    assert any("appears 2 times" in i.message for i in issues)


def test_modrinth_index_json_not_valid_utf8(mrpack_factory):
    path = mrpack_factory(raw_index_entries=[("modrinth.index.json", b"\xff\xfe\x00not utf8")])
    issues = mv.validate_archive(path, expected_mc="1.20.1", expected_forge="47.4.10")
    assert any("not valid UTF-8" in i.message for i in issues)


def test_modrinth_index_json_not_valid_json(mrpack_factory):
    path = mrpack_factory(raw_index_entries=[("modrinth.index.json", b"{not json")])
    issues = mv.validate_archive(path, expected_mc="1.20.1", expected_forge="47.4.10")
    assert any("not valid JSON" in i.message for i in issues)


def test_wrong_format_version_and_game(mrpack_factory):
    index = valid_index(formatVersion=2, game="bedrock")
    path = mrpack_factory(index=index)
    issues = mv.validate_archive(path, expected_mc="1.20.1", expected_forge="47.4.10")
    messages = " ".join(i.message for i in issues)
    assert "formatVersion" in messages
    assert "game" in messages


def test_wrong_minecraft_or_forge_dependency(mrpack_factory):
    index = valid_index(dependencies={"minecraft": "1.19.2", "forge": "45.0.0"})
    path = mrpack_factory(index=index)
    issues = mv.validate_archive(path, expected_mc="1.20.1", expected_forge="47.4.10")
    messages = " ".join(i.message for i in issues)
    assert "minecraft" in messages
    assert "forge" in messages


def test_malformed_hashes(mrpack_factory):
    index = valid_index(files=[valid_file_entry(hashes={"sha1": "not-hex", "sha512": "tooshort"})])
    path = mrpack_factory(index=index)
    issues = mv.validate_archive(path, expected_mc="1.20.1", expected_forge="47.4.10")
    assert "checksum" in _categories(issues)


def test_incorrect_file_size(mrpack_factory):
    for bad_size in (0, -5, "not-a-number", None):
        index = valid_index(files=[valid_file_entry(fileSize=bad_size)])
        archive = mrpack_factory(index=index)
        issues = mv.validate_archive(archive, expected_mc="1.20.1", expected_forge="47.4.10")
        assert any("fileSize" in i.message for i in issues), bad_size


def test_invalid_env_values(mrpack_factory):
    index = valid_index(files=[valid_file_entry(env={"client": "sometimes", "server": "required"})])
    path = mrpack_factory(index=index)
    issues = mv.validate_archive(path, expected_mc="1.20.1", expected_forge="47.4.10")
    assert any("env.client" in i.message for i in issues)


def test_download_url_wrong_domain(mrpack_factory):
    index = valid_index(files=[valid_file_entry(downloads=["https://evil.example.com/mods/test.jar"])])
    path = mrpack_factory(index=index)
    issues = mv.validate_archive(path, expected_mc="1.20.1", expected_forge="47.4.10")
    assert any("not in the allowed domain list" in i.message for i in issues)


def test_download_url_not_https(mrpack_factory):
    index = valid_index(files=[valid_file_entry(downloads=["http://cdn.modrinth.com/data/a/versions/b/c.jar"])])
    path = mrpack_factory(index=index)
    issues = mv.validate_archive(path, expected_mc="1.20.1", expected_forge="47.4.10")
    assert any("not HTTPS" in i.message for i in issues)


def test_no_downloads_declared(mrpack_factory):
    index = valid_index(files=[valid_file_entry(downloads=[])])
    path = mrpack_factory(index=index)
    issues = mv.validate_archive(path, expected_mc="1.20.1", expected_forge="47.4.10")
    assert any("no downloads" in i.message for i in issues)


class TestPathSecurity:
    @staticmethod
    def _violations_for(raw_path: str) -> list[str]:
        return mv.validate_relative_path(raw_path)

    def test_parent_traversal(self):
        assert self._violations_for("mods/../../../etc/passwd")

    def test_absolute_leading_slash(self):
        assert self._violations_for("/etc/passwd")

    def test_windows_drive_path(self):
        assert self._violations_for("C:/Windows/System32/evil.dll")
        assert self._violations_for("C:\\Windows\\System32\\evil.dll")

    def test_leading_backslash(self):
        assert self._violations_for("\\evil.dll")

    def test_backslash_traversal(self):
        assert self._violations_for("mods\\..\\..\\evil.jar")

    def test_empty_path_component(self):
        assert self._violations_for("mods//evil.jar")
        assert self._violations_for("mods/evil.jar/")

    def test_windows_reserved_names(self):
        for reserved in ("CON", "con.txt", "PRN", "AUX", "NUL", "COM1", "LPT1"):
            assert self._violations_for(f"mods/{reserved}"), reserved

    def test_normal_path_is_clean(self):
        assert self._violations_for("mods/create-1.20.1-6.0.8.jar") == []
        assert self._violations_for("config/some-mod/settings.toml") == []


def test_path_traversal_in_declared_index_file(mrpack_factory):
    index = valid_index(files=[valid_file_entry(path="../../../outside.jar")])
    path = mrpack_factory(index=index)
    issues = mv.validate_archive(path, expected_mc="1.20.1", expected_forge="47.4.10")
    assert any("unsafe path" in i.message for i in issues)


def test_path_traversal_in_override_zip_entry(mrpack_factory):
    path = mrpack_factory(extra_entries={"overrides/../../evil.txt": b"data"})
    issues = mv.validate_archive(path, expected_mc="1.20.1", expected_forge="47.4.10")
    assert any("unsafe path" in i.message for i in issues)


def test_duplicate_zip_entries(mrpack_factory, tmp_path):
    import zipfile

    archive_path = tmp_path / "dup.mrpack"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("modrinth.index.json", '{"game":"minecraft","formatVersion":1,"versionId":"x","name":"x","files":[],"dependencies":{"minecraft":"1.20.1","forge":"47.4.10"}}')
        zf.writestr("overrides/config/a.toml", b"one")
        zf.writestr("overrides/config/a.toml", b"two")
    issues = mv.validate_archive(archive_path, expected_mc="1.20.1", expected_forge="47.4.10")
    assert any("duplicate ZIP entry" in i.message for i in issues)


def test_case_insensitive_collision(mrpack_factory):
    index = valid_index(
        files=[
            valid_file_entry(path="mods/Foo.jar", hashes={"sha1": "a" * 40, "sha512": "b" * 128}),
        ]
    )
    path = mrpack_factory(index=index, extra_entries={"overrides/mods/foo.jar": b"data"})
    issues = mv.validate_archive(path, expected_mc="1.20.1", expected_forge="47.4.10")
    assert any("case-insensitive path collision" in i.message for i in issues)


def test_override_collides_with_indexed_file(mrpack_factory):
    index = valid_index(files=[valid_file_entry(path="mods/test-mod.jar")])
    path = mrpack_factory(index=index, extra_entries={"overrides/mods/test-mod.jar": b"data"})
    issues = mv.validate_archive(path, expected_mc="1.20.1", expected_forge="47.4.10")
    assert any("collides with an indexed downloadable file" in i.message for i in issues)


def test_client_server_override_drift_is_a_warning_not_fatal(mrpack_factory):
    path = mrpack_factory(
        extra_entries={
            "client-overrides/config/shared.toml": b"same",
            "server-overrides/config/shared.toml": b"same",
        }
    )
    issues = mv.check_override_layering(mv.load_archive(path)[0].names)
    assert len(issues) == 1
    assert issues[0].fatal is False


def test_no_test_artifacts_detects_disallowed_markers(mrpack_factory):
    index = valid_index(files=[valid_file_entry(path="mods/chunky-1.3.146.jar")])
    path = mrpack_factory(index=index)
    issues = mv.validate_archive(path, expected_mc="1.20.1", expected_forge="47.4.10")
    assert any("test-only marker" in i.message for i in issues)


def test_manifest_index_agreement_detects_orphans(mrpack_factory):
    manifest = {
        "resolved_mods": [
            {
                "path": "mods/other.jar",
                "sha1": "c" * 40,
                "sha512": "d" * 128,
                "file_size": 999,
                "env": {"client": "required", "server": "required"},
            }
        ]
    }
    index = valid_index(files=[valid_file_entry(path="mods/test-mod.jar")])
    path = mrpack_factory(index=index)
    issues = mv.validate_archive(path, manifest=manifest, expected_mc="1.20.1", expected_forge="47.4.10")
    messages = " ".join(i.message for i in issues)
    assert "missing from modrinth.index.json" in messages
    assert "missing from manifest.json" in messages
