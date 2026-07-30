"""Batch hash verification against the official Modrinth API.

Uses ``POST /v2/version_files`` (see
https://docs.modrinth.com/api/operations/versionsfromhashes/) to confirm
that every *Modrinth-hosted* file in the built index really is the file
Modrinth's database says it is, and that the matched version supports
Minecraft 1.20.1 + Forge.

Files hosted off Modrinth's CDN (currently none in this pack, but the
format explicitly permits github.com/raw.githubusercontent.com/gitlab.com)
are intentionally NOT required to resolve here -- their URL/hash syntax is
validated by mrpack_validate.py instead. See Phase 3 spec: "Do not require
every external GitHub-hosted file to resolve as a Modrinth project."
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .mrpack_validate import Issue

API_BASE = "https://api.modrinth.com/v2"
USER_AGENT = "Aeronautica-Wandering-City-TestPipeline/1.0 (+modrinth-hash-verify; contact via github.com/edumi8)"
BATCH_SIZE = 50


@dataclass
class HashLookupEntry:
    path: str
    sha512: str
    is_modrinth_hosted: bool


def _post_json(url: str, payload: dict[str, Any], *, timeout: float = 60.0) -> Any:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https API_BASE
        return json.loads(response.read().decode("utf-8"))


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def verify_index_against_modrinth(
    index: dict[str, Any], *, expected_mc: str, expected_forge_loader: str = "forge", timeout: float = 60.0
) -> list[Issue]:
    """For every file whose declared download host is cdn.modrinth.com, look
    it up by sha512 via the batch endpoint and confirm:
      - the hash is known to Modrinth at all;
      - the matched version's game_versions include ``expected_mc``;
      - the matched version's loaders include ``expected_forge_loader``.
    """
    entries: list[HashLookupEntry] = []
    for file_entry in index.get("files", []):
        path = file_entry.get("path", "<missing path>")
        sha512 = file_entry.get("hashes", {}).get("sha512", "")
        downloads = file_entry.get("downloads") or []
        hosted_on_modrinth = any("cdn.modrinth.com" in url for url in downloads)
        entries.append(HashLookupEntry(path=path, sha512=sha512, is_modrinth_hosted=hosted_on_modrinth))

    modrinth_entries = [e for e in entries if e.is_modrinth_hosted and e.sha512]
    if not modrinth_entries:
        return []

    hash_to_entry = {e.sha512.lower(): e for e in modrinth_entries}
    issues: list[Issue] = []

    for batch in _chunks(list(hash_to_entry.keys()), BATCH_SIZE):
        try:
            response = _post_json(
                f"{API_BASE}/version_files", {"hashes": batch, "algorithm": "sha512"}, timeout=timeout
            )
        except (urllib.error.URLError, TimeoutError) as exc:
            issues.append(
                Issue(
                    category="checksum",
                    message=f"Modrinth version_files lookup failed for a batch of {len(batch)} hashes: {exc}",
                )
            )
            continue

        for sha512 in batch:
            entry = hash_to_entry[sha512]
            version = response.get(sha512)
            if version is None:
                issues.append(
                    Issue(
                        category="checksum",
                        message="sha512 not recognized by Modrinth's version_files API "
                        "(file may have been removed/re-uploaded upstream)",
                        path=entry.path,
                    )
                )
                continue
            game_versions = version.get("game_versions", [])
            loaders = version.get("loaders", [])
            if expected_mc not in game_versions:
                issues.append(
                    Issue(
                        category="checksum",
                        message=f"Modrinth-matched version {version.get('version_number')} does not list "
                        f"Minecraft {expected_mc} in game_versions={game_versions}",
                        path=entry.path,
                    )
                )
            if expected_forge_loader not in loaders:
                issues.append(
                    Issue(
                        category="checksum",
                        message=f"Modrinth-matched version {version.get('version_number')} does not list "
                        f"loader {expected_forge_loader!r} in loaders={loaders}",
                        path=entry.path,
                    )
                )
    return issues
