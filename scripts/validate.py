#!/usr/bin/env python3
"""Validate and build the Aeronautica Modrinth pack."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aeronautica_testing.compat import verify_core_compatibility as _verify_core_compatibility  # noqa: E402

API = "https://api.modrinth.com/v2"
USER_AGENT = "Aeronautica-Wandering-City/0.1.0-alpha.3 (build validator)"

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "modpack" / "manifest.json"
INDEX_PATH = ROOT / "modpack" / "modrinth.index.json"
ICON_PATH = ROOT / "modpack" / "icon.png"
OVERRIDES_PATH = ROOT / "overrides"
RELEASES_PATH = ROOT / "releases"

# Fixed archive timestamp/permissions so two builds of identical logical
# content produce byte-identical .mrpack/.zip files regardless of when or on
# which OS they were built. Honors SOURCE_DATE_EPOCH
# (https://reproducible-builds.org/docs/source-date-epoch/) when set.
_FILE_EXTERNAL_ATTR = 0o644 << 16


def _reproducible_date_time() -> tuple[int, int, int, int, int, int]:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        import time

        return tuple(time.gmtime(int(epoch))[:6])  # type: ignore[return-value]
    return (2020, 1, 1, 0, 0, 0)


def _write_deterministic(archive: zipfile.ZipFile, arcname: str, data: bytes) -> None:
    info = zipfile.ZipInfo(arcname, date_time=_reproducible_date_time())
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = _FILE_EXTERNAL_ATTR
    archive.writestr(info, data)


def _iter_sorted_files(base: Path):
    for path in sorted(base.rglob("*")):
        if path.is_file():
            yield path


def request_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.load(response)


def open_response(url: str) -> urllib.response.addinfourl:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(request, timeout=180)


def _report_resolved_count_drift(new_count: int) -> None:
    """The set of resolved mod files is never hard-coded (see repository
    invariants); instead a run that changes the count is surfaced as an
    informational note derived from whatever modrinth.index.json already
    contains on disk, so drift is visible without blocking legitimate
    mod additions/removals.
    """
    if not INDEX_PATH.exists():
        return
    try:
        previous_index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    previous_count = len(previous_index.get("files", []))
    if previous_count and previous_count != new_count:
        print(
            f"NOTE: resolved mod file count changed from {previous_count} to {new_count} "
            "(dependency resolution drift -- review before releasing).",
            file=sys.stderr,
        )


def load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(f"Missing manifest: {MANIFEST_PATH}")
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def select_version(identifier: str, pinned: str | None) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {"loaders": json.dumps(["forge"]), "game_versions": json.dumps(["1.20.1"])}
    )
    versions = request_json(f"{API}/project/{urllib.parse.quote(identifier)}/version?{query}")
    if pinned:
        for version in versions:
            if version.get("version_number") == pinned or version.get("name") == pinned:
                return version
        raise RuntimeError(f"Pinned version not found for {identifier}: {pinned}")
    releases = [version for version in versions if version.get("version_type") == "release"]
    candidates = releases or versions
    if not candidates:
        raise RuntimeError(f"No Forge 1.20.1 version found for project: {identifier}")
    return candidates[0]


def project_details(project_id_or_slug: str) -> dict[str, Any]:
    return request_json(f"{API}/project/{urllib.parse.quote(project_id_or_slug)}")


def primary_file(version: dict[str, Any]) -> dict[str, Any]:
    files = version.get("files", [])
    for file in files:
        if file.get("primary"):
            return file
    if not files:
        raise RuntimeError(f"Version {version.get('id')} has no downloadable files")
    return files[0]


def infer_env(project: dict[str, Any]) -> dict[str, str]:
    client = project.get("client_side") or "required"
    server = project.get("server_side") or "required"
    return {"client": client, "server": server}


def hash_remote_file(url: str) -> tuple[str, int]:
    digest = hashlib.sha512()
    total = 0
    with open_response(url) as response:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
    return digest.hexdigest(), total


def verify_structure(manifest: dict[str, Any]) -> None:
    if manifest.get("loader") != "forge":
        raise RuntimeError("Only Forge is supported by this pack.")
    if manifest.get("minecraft") != "1.20.1":
        raise RuntimeError("This pack is locked to Minecraft 1.20.1.")
    if manifest.get("forge_version") != "47.4.10":
        raise RuntimeError("This pack is locked to Forge 47.4.10.")
    if not ICON_PATH.exists():
        raise FileNotFoundError(f"Missing pack icon: {ICON_PATH}")
    if not OVERRIDES_PATH.exists():
        raise FileNotFoundError(f"Missing overrides directory: {OVERRIDES_PATH}")


def build_resolved_manifest(manifest: dict[str, Any], verify_downloads: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    source_mods = [mod for mod in manifest.get("mods", []) if not mod.get("todo")]
    explicit_pins = {mod["slug"]: mod.get("version") for mod in source_mods if mod.get("version")}

    selected_by_slug: dict[str, dict[str, Any]] = {}
    selected_by_project_id: dict[str, str] = {}

    def register_version(version: dict[str, Any], identifier: str) -> None:
        project_id = version.get("project_id")
        if not project_id:
            raise RuntimeError(f"Version {version.get('id')} is missing project_id")
        project = project_details(project_id)
        slug = project.get("slug", identifier)

        if slug in selected_by_slug:
            existing = selected_by_slug[slug]
            if existing.get("id") != version.get("id"):
                raise RuntimeError(
                    f"Conflicting dependency versions for {slug}: {existing.get('version_number')} vs {version.get('version_number')}"
                )
            return

        if project_id in selected_by_project_id:
            existing_slug = selected_by_project_id[project_id]
            if existing_slug != slug:
                raise RuntimeError(f"Conflicting projects for {project_id}: {existing_slug} vs {slug}")
            return

        selected_by_slug[slug] = version
        selected_by_project_id[project_id] = slug

        for dependency in version.get("dependencies", []):
            if dependency.get("dependency_type") != "required":
                continue
            dep_version_id = dependency.get("version_id")
            if dep_version_id:
                dep_version = request_json(f"{API}/version/{urllib.parse.quote(dep_version_id)}")
                register_version(dep_version, dep_version_id)
                continue

            dep_project = dependency.get("project_id")
            if not dep_project:
                continue
            dep_project_info = project_details(dep_project)
            dep_slug = dep_project_info.get("slug", dep_project)
            if dep_slug in selected_by_slug or dep_project in selected_by_project_id:
                continue
            pinned = explicit_pins.get(dep_slug)
            dep_version = select_version(dep_project, pinned)
            register_version(dep_version, dep_slug)

    for source_mod in source_mods:
        version = select_version(source_mod["slug"], source_mod.get("version"))
        register_version(version, source_mod["slug"])

    versions_by_slug = {slug: version.get("version_number", "") for slug, version in selected_by_slug.items()}
    _verify_core_compatibility(versions_by_slug, explicit_pins)

    resolved_mods: list[dict[str, Any]] = []
    for slug, version in selected_by_slug.items():
        project_id = version.get("project_id")
        if not project_id:
            raise RuntimeError(f"Version {version.get('id')} is missing project_id")
        project = project_details(project_id)
        file = primary_file(version)
        sha512 = file.get("hashes", {}).get("sha512")
        sha1 = file.get("hashes", {}).get("sha1")
        if not sha512 or not sha1:
            raise RuntimeError(f"Missing checksums for {project_id} {version.get('id')}")
        if verify_downloads:
            verified_sha512, _ = hash_remote_file(file["url"])
            if verified_sha512.lower() != sha512.lower():
                raise RuntimeError(f"SHA-512 mismatch for {file.get('filename')}")
        resolved_mods.append(
            {
                "slug": project.get("slug", slug),
                "project_id": project_id,
                "project_title": project.get("title"),
                "version_id": version.get("id"),
                "version_number": version.get("version_number"),
                "download_url": file.get("url"),
                "filename": file.get("filename"),
                "path": f"mods/{file.get('filename')}",
                "file_size": file.get("size"),
                "sha1": sha1,
                "sha512": sha512,
                "client_side": project.get("client_side"),
                "server_side": project.get("server_side"),
                "env": infer_env(project),
                "requested_version": explicit_pins.get(project.get("slug", slug)),
            }
        )

    if not resolved_mods:
        raise RuntimeError("Dependency resolution produced zero mod files.")
    _report_resolved_count_drift(len(resolved_mods))

    resolved_mods.sort(key=lambda item: item["path"].lower())
    resolved_manifest = dict(manifest)
    resolved_manifest["resolved_mods"] = resolved_mods
    index = {
        "game": "minecraft",
        "formatVersion": 1,
        "versionId": manifest["version"],
        "name": manifest["name"],
        "summary": manifest.get("description"),
        "files": [
            {
                "path": mod["path"],
                "hashes": {"sha1": mod["sha1"], "sha512": mod["sha512"]},
                "env": mod["env"],
                "downloads": [mod["download_url"]],
                "fileSize": mod["file_size"],
            }
            for mod in resolved_mods
        ],
        "dependencies": {
            "minecraft": manifest["minecraft"],
            "forge": manifest["forge_version"],
        },
    }
    return resolved_manifest, index


def write_release_archive(index: dict[str, Any], release_name: str, output_dir: Path = RELEASES_PATH) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    mrpack_path = output_dir / f"{release_name}.mrpack"
    with zipfile.ZipFile(mrpack_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        _write_deterministic(archive, "modrinth.index.json", (json.dumps(index, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
        _write_deterministic(archive, "icon.png", ICON_PATH.read_bytes())
        for source in _iter_sorted_files(OVERRIDES_PATH):
            relative = source.relative_to(OVERRIDES_PATH).as_posix()
            _write_deterministic(archive, f"overrides/{relative}", source.read_bytes())
    return mrpack_path


def write_manual_zip(release_name: str, index: dict[str, Any], output_dir: Path = RELEASES_PATH) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / f"{release_name}-manual.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        _write_deterministic(archive, "modrinth.index.json", (json.dumps(index, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
        _write_deterministic(archive, "manifest.json", MANIFEST_PATH.read_bytes())
        _write_deterministic(archive, "icon.png", ICON_PATH.read_bytes())
        for source in _iter_sorted_files(OVERRIDES_PATH):
            relative = source.relative_to(OVERRIDES_PATH).as_posix()
            _write_deterministic(archive, f"overrides/{relative}", source.read_bytes())
    return zip_path


def write_sha256_sums(artefacts: list[Path], output_dir: Path = RELEASES_PATH) -> Path:
    sha_path = output_dir / "SHA256SUMS"
    lines = []
    for artefact in sorted(artefacts, key=lambda p: p.name):
        digest = hashlib.sha256(artefact.read_bytes()).hexdigest()
        lines.append(f"{digest}  {artefact.name}")
    sha_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return sha_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and build the Aeronautica Modrinth pack.")
    parser.add_argument("--build", action="store_true", help="Write modpack/modrinth.index.json and build the release artefacts")
    parser.add_argument("--verify-downloads", action="store_true", help="Download every file and verify its SHA-512 checksum against Modrinth")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=RELEASES_PATH,
        help="Directory to write the .mrpack/manual zip/SHA256SUMS into (default: releases/). "
        "Used by the reproducible-build test to build twice into isolated directories.",
    )
    args = parser.parse_args()

    manifest = load_manifest()
    verify_structure(manifest)

    verify_downloads = args.verify_downloads or args.build
    resolved_manifest, index = build_resolved_manifest(manifest, verify_downloads)

    save_json(MANIFEST_PATH, resolved_manifest)
    save_json(INDEX_PATH, index)

    if args.build:
        release_name = f"{manifest['name'].replace(':', '').replace(' ', '-')}-{manifest['version']}"
        mrpack_path = write_release_archive(index, release_name, output_dir=args.output_dir)
        manual_zip_path = write_manual_zip(release_name, index, output_dir=args.output_dir)
        sha_path = write_sha256_sums([mrpack_path, manual_zip_path], output_dir=args.output_dir)
        print(f"Built {mrpack_path}")
        print(f"Built {manual_zip_path}")
        print(f"Wrote {sha_path}")

    print(f"Validated {len(index['files'])} mod files.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Validation cancelled.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

