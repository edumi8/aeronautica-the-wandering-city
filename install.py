#!/usr/bin/env python3
"""Install Aeronautica mods into an existing Forge 1.20.1 instance.

The installer prefers the resolved pack manifest when present, falls back to
live Modrinth resolution when needed, and never deletes existing files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

API = "https://api.modrinth.com/v2"
MC_VERSION = "1.20.1"
LOADER = "forge"
USER_AGENT = "Aeronautica-Wandering-City/0.1.0-alpha.1 (local installer)"


def request_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def get_versions(identifier: str) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode(
        {"loaders": json.dumps([LOADER]), "game_versions": json.dumps([MC_VERSION])}
    )
    return request_json(f"{API}/project/{urllib.parse.quote(identifier)}/version?{query}")


def select_version(identifier: str, pinned: str | None) -> dict[str, Any]:
    versions = get_versions(identifier)
    if pinned:
        for version in versions:
            if version.get("version_number") == pinned or version.get("name") == pinned:
                return version
        raise RuntimeError(f"Pinned version not found for {identifier}: {pinned}")

    releases = [version for version in versions if version.get("version_type") == "release"]
    candidates = releases or versions
    if not candidates:
        raise RuntimeError(f"No Forge {MC_VERSION} version found for project: {identifier}")
    return candidates[0]


def primary_file(version: dict[str, Any]) -> dict[str, Any]:
    files = version.get("files", [])
    for file in files:
        if file.get("primary"):
            return file
    if not files:
        raise RuntimeError(f"Version {version.get('id')} has no downloadable files")
    return files[0]


def download_file(url: str, destination: Path, expected_sha512: str | None) -> None:
    temporary = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha512()
    with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
            digest.update(chunk)
    actual = digest.hexdigest()
    if expected_sha512 and actual.lower() != expected_sha512.lower():
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"SHA-512 mismatch for {destination.name}")
    temporary.replace(destination)


def load_manifest(root: Path) -> dict[str, Any]:
    manifest_path = root / "modpack" / "manifest.json"
    if not manifest_path.exists():
        manifest_path = root / "mods.json"
    if not manifest_path.exists():
        raise FileNotFoundError("Could not find modpack/manifest.json or mods.json")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def resolve_from_live(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    source_mods = [mod for mod in (manifest.get("mods") or []) if not mod.get("todo")]
    if not source_mods:
        source_mods = [
        {"slug": slug, "version": manifest.get("pinned", {}).get(slug)}
        for slug in manifest.get("projects", [])
    ]

    selected: dict[str, dict[str, Any]] = {}
    queue: list[tuple[str, str | None]] = [(mod["slug"], mod.get("version")) for mod in source_mods]

    print(f"Resolving Aeronautica for Minecraft {MC_VERSION} / {LOADER}...")
    while queue:
        identifier, pinned = queue.pop(0)
        if identifier in selected:
            continue
        version = select_version(identifier, pinned)
        project_id = version.get("project_id")
        if not project_id:
            raise RuntimeError(f"Version {version.get('id')} is missing project_id")
        selected[project_id] = version
        print(f"  {identifier}: {version['version_number']}")

        for dependency in version.get("dependencies", []):
            if dependency.get("dependency_type") != "required":
                continue
            dep_project = dependency.get("project_id")
            dep_version = dependency.get("version_id")
            if dep_project and dep_project not in selected:
                if dep_version:
                    dep_data = request_json(f"{API}/version/{urllib.parse.quote(dep_version)}")
                    dep_project_id = dep_data.get("project_id")
                    if not dep_project_id:
                        raise RuntimeError(f"Dependency version {dep_version} is missing project_id")
                    selected[dep_project_id] = dep_data
                    print(f"  dependency {dep_project_id}: {dep_data['version_number']}")
                else:
                    queue.append((dep_project, None))
        time.sleep(0.05)

    resolved_mods: list[dict[str, Any]] = []
    for project_id, version in selected.items():
        file = primary_file(version)
        project = request_json(f"{API}/project/{urllib.parse.quote(project_id)}")
        hashes = file.get("hashes", {})
        sha512 = hashes.get("sha512")
        sha1 = hashes.get("sha1")
        if not sha512 or not sha1:
            raise RuntimeError(f"Missing checksums for {project_id} {version.get('id')}")
        resolved_mods.append(
            {
                "slug": project.get("slug", project_id),
                "project_id": project_id,
                "project_title": project.get("title"),
                "version_id": version.get("id"),
                "version_number": version.get("version_number"),
                "download_url": file.get("url"),
                "filename": file.get("filename"),
                "sha1": sha1,
                "sha512": sha512,
                "file_size": file.get("size"),
                "client_side": project.get("client_side"),
                "server_side": project.get("server_side"),
            }
        )

    return sorted(resolved_mods, key=lambda item: item["filename"].lower())


def install_from_manifest(root: Path, instance: Path, dry_run: bool) -> int:
    manifest = load_manifest(root)
    instance = instance.expanduser().resolve()
    mods_dir = instance / "mods"
    mods_dir.mkdir(parents=True, exist_ok=True)

    selected_mods = manifest.get("resolved_mods") or []
    if not selected_mods:
        selected_mods = resolve_from_live(manifest)

    lock = {
        "minecraft": MC_VERSION,
        "loader": LOADER,
        "generated_by": "Aeronautica installer 0.1.0-alpha.1",
        "mods": [
            {
                "project_id": item["project_id"],
                "version_id": item["version_id"],
                "version": item["version_number"],
                "filename": item["filename"],
                "url": item["download_url"],
                "sha512": item["sha512"],
            }
            for item in selected_mods
        ],
    }

    lock["mods"].sort(key=lambda item: item["filename"].lower())
    (instance / "aeronautica-lock.json").write_text(json.dumps(lock, indent=2), encoding="utf-8")

    if dry_run:
        print(f"Resolved {len(lock['mods'])} files. Lock file written; no downloads performed.")
        return 0

    for item in lock["mods"]:
        destination = mods_dir / item["filename"]
        if destination.exists():
            existing = hashlib.sha512(destination.read_bytes()).hexdigest()
            if existing.lower() == (item["sha512"] or "").lower():
                print(f"  already present: {destination.name}")
                continue
            print(f"  keeping existing conflicting file: {destination.name}")
            destination = mods_dir / f"aeronautica-{destination.name}"
        print(f"  downloading: {destination.name}")
        download_file(item["url"], destination, item["sha512"])

    overrides = root / "overrides"
    if overrides.exists():
        shutil.copytree(overrides, instance, dirs_exist_ok=True)

    print("\nInstallation complete.")
    print("Use Java 17, Forge 47.4.10, and allocate 8-10 GB of RAM.")
    print("Back up worlds before moving large ships. This is an experimental alpha build.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Install Aeronautica into a Forge 1.20.1 instance.")
    parser.add_argument(
        "instance",
        type=Path,
        help="Path to the Minecraft instance directory from Prism Launcher or PollyMC",
    )
    parser.add_argument("--dry-run", action="store_true", help="Resolve the pack without downloading files")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    return install_from_manifest(root, args.instance, args.dry_run)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Installation cancelled.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
