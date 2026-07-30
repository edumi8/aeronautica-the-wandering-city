"""Deep structural and security validation of a built .mrpack / manual ZIP.

This module never trusts the code that *produced* the artifact -- it is
deliberately independent of ``scripts/validate.py`` so a bug shared by both
build and validation logic cannot silently pass. Every check returns a list
of :class:`Issue` instead of raising, so a single run can surface every
problem in a malicious/malformed fixture instead of stopping at the first.

Primary source for the format rules encoded here:
https://support.modrinth.com/en/articles/8802351-modrinth-modpack-format-mrpack
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# --- Modrinth format constants (see module docstring for source) ----------

ALLOWED_DOWNLOAD_DOMAINS = frozenset(
    {"cdn.modrinth.com", "github.com", "raw.githubusercontent.com", "gitlab.com"}
)

# Hosts that first-party origins are known to legitimately redirect to.
# Kept intentionally small: anything not listed here must resolve to one of
# ALLOWED_DOWNLOAD_DOMAINS itself, or the redirect is rejected.
ALLOWED_REDIRECT_TARGET_SUFFIXES: dict[str, tuple[str, ...]] = {
    "github.com": (".githubusercontent.com", "github.com"),
    "raw.githubusercontent.com": (".githubusercontent.com", "raw.githubusercontent.com"),
    "gitlab.com": (".gitlab.com", "gitlab.com"),
    "cdn.modrinth.com": ("cdn.modrinth.com",),
}

VALID_ENV_VALUES = frozenset({"required", "optional", "unsupported"})

_RESERVED_WINDOWS_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA512_RE = re.compile(r"^[0-9a-f]{128}$")

# Slugs/filenames that must never ship in a release artifact -- test-only
# tooling (GameTest QA helper, HeadlessMC injected mod, worldgen profilers).
DISALLOWED_TEST_MARKERS = frozenset(
    {
        "aeronautica-gametest",
        "aeronauticagametest",
        "headlessmc",
        "hmc-todo-remover",
        "chunky",
        "spark",
    }
)

USER_AGENT = "Aeronautica-Wandering-City-TestPipeline/1.0 (+mrpack-validate)"


@dataclass
class Issue:
    category: str
    message: str
    path: str | None = None
    fatal: bool = True

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return f"[{self.category}] {self.message}" + (f" ({self.path})" if self.path else "")


def _issue(category: str, message: str, path: str | None = None) -> Issue:
    return Issue(category=category, message=message, path=path)


# --- Path safety -------------------------------------------------------


def validate_relative_path(raw_path: str) -> list[str]:
    """Return a list of human-readable violations for a single declared or
    archived relative path. Empty list means the path is safe.
    """
    violations: list[str] = []
    if raw_path == "":
        return ["path is empty"]
    if "\\" in raw_path:
        violations.append("contains a backslash (paths must be POSIX-style forward-slash)")
    if raw_path.startswith("/") or raw_path.startswith("\\"):
        violations.append("starts with a leading slash")
    if re.match(r"^[A-Za-z]:[\\/]", raw_path):
        violations.append("is a Windows drive-letter absolute path")
    if raw_path.startswith("\\\\") or raw_path.startswith("//"):
        violations.append("is a UNC/protocol-relative style path")

    components = re.split(r"[\\/]", raw_path)
    for component in components:
        if component == "":
            violations.append("contains an empty path component (double slash or trailing slash)")
            continue
        if component == "." or component == "..":
            violations.append(f"contains a traversal component ({component!r})")
            continue
        stem = component.split(".", 1)[0].upper()
        if stem in _RESERVED_WINDOWS_NAMES:
            violations.append(f"contains a Windows reserved device name ({component!r})")

    # De-duplicate while preserving order.
    seen: set[str] = set()
    unique = []
    for v in violations:
        if v not in seen:
            seen.add(v)
            unique.append(v)
    return unique


def check_paths_security(paths: dict[str, str]) -> list[Issue]:
    """``paths`` maps a display label (e.g. "index:mods/foo.jar" or
    "zip-entry:overrides/config/x.toml") to the raw path string to check.
    """
    issues: list[Issue] = []
    for label, raw_path in paths.items():
        for violation in validate_relative_path(raw_path):
            issues.append(_issue("artifact", f"unsafe path -- {violation}", path=label))
    return issues


def check_duplicate_and_case_collisions(paths: dict[str, list[str]]) -> list[Issue]:
    """``paths`` maps a normalized *installed* relative path to the list of
    labels/layers that would write to it. Flags exact duplicates within the
    same layer set and case-insensitive collisions across the whole tree.
    """
    issues: list[Issue] = []
    for normalized, labels in paths.items():
        if len(labels) > 1:
            # Multiple contributors to the exact same target path from the
            # same namespace (e.g. two "mods/foo.jar" file entries, or the
            # same override file appearing twice in the zip) is unambiguous
            # data corruption.
            same_layer = _same_layer(labels)
            if same_layer:
                issues.append(
                    _issue(
                        "artifact",
                        f"duplicate target path from {len(labels)} entries: {labels}",
                        path=normalized,
                    )
                )

    by_casefold: dict[str, list[str]] = {}
    for normalized in paths:
        by_casefold.setdefault(normalized.casefold(), []).append(normalized)
    for _, variants in by_casefold.items():
        if len(variants) > 1:
            issues.append(
                _issue(
                    "artifact",
                    f"case-insensitive path collision between {sorted(variants)} "
                    "(unsafe on Windows/macOS default filesystems)",
                    path=variants[0],
                )
            )
    return issues


def _same_layer(labels: list[str]) -> bool:
    layers = {label.split(":", 1)[0] for label in labels}
    return len(layers) == 1


# --- Archive-level structure --------------------------------------------


@dataclass
class LoadedArtifact:
    archive_path: Path
    zip_file: zipfile.ZipFile
    names: list[str]
    index: dict[str, Any] | None
    index_issues: list[Issue] = field(default_factory=list)


def load_archive(archive_path: Path) -> tuple[LoadedArtifact | None, list[Issue]]:
    issues: list[Issue] = []
    if not archive_path.exists():
        return None, [_issue("artifact", f"archive does not exist: {archive_path}")]
    if not zipfile.is_zipfile(archive_path):
        return None, [_issue("artifact", f"{archive_path} is not a valid ZIP archive")]

    zip_file = zipfile.ZipFile(archive_path)
    bad_entry = zip_file.testzip()
    if bad_entry is not None:
        issues.append(_issue("artifact", f"corrupt ZIP member (CRC mismatch): {bad_entry}"))

    names = zip_file.namelist()
    index_occurrences = [n for n in names if n == "modrinth.index.json"]
    index: dict[str, Any] | None = None
    if len(index_occurrences) == 0:
        issues.append(_issue("artifact", "modrinth.index.json is absent from the archive root"))
    elif len(index_occurrences) > 1:
        issues.append(
            _issue(
                "artifact",
                f"modrinth.index.json appears {len(index_occurrences)} times (must be exactly once)",
            )
        )
    else:
        raw = zip_file.read("modrinth.index.json")
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            issues.append(_issue("manifest", f"modrinth.index.json is not valid UTF-8: {exc}"))
            text = None
        if text is not None:
            try:
                index = json.loads(text)
            except json.JSONDecodeError as exc:
                issues.append(_issue("manifest", f"modrinth.index.json is not valid JSON: {exc}"))

    artifact = LoadedArtifact(archive_path=archive_path, zip_file=zip_file, names=names, index=index)
    return artifact, issues


def check_format_and_game(index: dict[str, Any]) -> list[Issue]:
    issues = []
    if index.get("formatVersion") != 1:
        issues.append(_issue("manifest", f"formatVersion must be 1, got {index.get('formatVersion')!r}"))
    if index.get("game") != "minecraft":
        issues.append(_issue("manifest", f"game must be 'minecraft', got {index.get('game')!r}"))
    for required_field in ("versionId", "name", "files", "dependencies"):
        if required_field not in index:
            issues.append(_issue("manifest", f"missing required top-level field: {required_field}"))
    return issues


def check_minecraft_and_forge_versions(
    index: dict[str, Any], *, expected_mc: str, expected_forge: str
) -> list[Issue]:
    issues = []
    deps = index.get("dependencies", {})
    mc = deps.get("minecraft")
    forge = deps.get("forge")
    if mc != expected_mc:
        issues.append(_issue("manifest", f"dependencies.minecraft must be exactly {expected_mc!r}, got {mc!r}"))
    if forge != expected_forge:
        issues.append(_issue("manifest", f"dependencies.forge must be exactly {expected_forge!r}, got {forge!r}"))
    return issues


def check_hash_and_size_syntax(index: dict[str, Any]) -> list[Issue]:
    issues = []
    for file_entry in index.get("files", []):
        path = file_entry.get("path", "<missing path>")
        hashes = file_entry.get("hashes", {})
        sha1 = hashes.get("sha1", "")
        sha512 = hashes.get("sha512", "")
        if not _SHA1_RE.match(sha1 or ""):
            issues.append(_issue("checksum", f"invalid/missing SHA-1 syntax: {sha1!r}", path=path))
        if not _SHA512_RE.match(sha512 or ""):
            issues.append(_issue("checksum", f"invalid/missing SHA-512 syntax: {sha512!r}", path=path))
        size = file_entry.get("fileSize")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            issues.append(_issue("artifact", f"fileSize must be a positive integer, got {size!r}", path=path))
    return issues


def check_env_values(index: dict[str, Any]) -> list[Issue]:
    issues = []
    for file_entry in index.get("files", []):
        path = file_entry.get("path", "<missing path>")
        env = file_entry.get("env")
        if env is None:
            continue  # env is optional per spec
        for side in ("client", "server"):
            value = env.get(side)
            if value not in VALID_ENV_VALUES:
                issues.append(
                    _issue(
                        "manifest",
                        f"env.{side} must be one of {sorted(VALID_ENV_VALUES)}, got {value!r}",
                        path=path,
                    )
                )
    return issues


def check_download_urls(index: dict[str, Any]) -> list[Issue]:
    issues = []
    for file_entry in index.get("files", []):
        path = file_entry.get("path", "<missing path>")
        downloads = file_entry.get("downloads", [])
        if not downloads:
            issues.append(_issue("download", "no downloads[] entries declared", path=path))
            continue
        for url in downloads:
            parsed = urllib.parse.urlsplit(url)
            if parsed.scheme != "https":
                issues.append(_issue("download", f"download URL is not HTTPS: {url!r}", path=path))
                continue
            if " " in url or not parsed.netloc:
                issues.append(_issue("download", f"malformed download URL: {url!r}", path=path))
                continue
            if parsed.hostname not in ALLOWED_DOWNLOAD_DOMAINS:
                issues.append(
                    _issue(
                        "download",
                        f"download host {parsed.hostname!r} is not in the allowed domain list "
                        f"{sorted(ALLOWED_DOWNLOAD_DOMAINS)}",
                        path=path,
                    )
                )
    return issues


def _override_roots(names: list[str]) -> dict[str, list[str]]:
    roots = {"overrides": [], "client-overrides": [], "server-overrides": []}
    for name in names:
        for root in roots:
            prefix = root + "/"
            if name.startswith(prefix) and not name.endswith("/"):
                roots[root].append(name[len(prefix) :])
    return roots


def check_override_collisions(names: list[str], index: dict[str, Any]) -> list[Issue]:
    issues = []
    indexed_paths = {f.get("path") for f in index.get("files", []) if f.get("path")}
    roots = _override_roots(names)
    for root, relative_paths in roots.items():
        for relative in relative_paths:
            if relative in indexed_paths:
                issues.append(
                    _issue(
                        "artifact",
                        f"{root}/{relative} collides with an indexed downloadable file at the same "
                        "install path -- ambiguous which one wins at install time",
                        path=relative,
                    )
                )
    return issues


def check_override_layering(names: list[str]) -> list[Issue]:
    """Flags a relative path present in *both* client-overrides and
    server-overrides as likely accidental drift (it should either live in
    base overrides/, or be intentionally different per side, not duplicated).
    Presence in both is a warning, not a hard failure, since the spec does
    not forbid it outright.
    """
    issues = []
    roots = _override_roots(names)
    client_set = set(roots["client-overrides"])
    server_set = set(roots["server-overrides"])
    shared = client_set & server_set
    for relative in sorted(shared):
        issues.append(
            Issue(
                category="artifact",
                message=(
                    f"{relative!r} exists in both client-overrides/ and server-overrides/ -- "
                    "if the content is identical it belongs in overrides/ instead"
                ),
                path=relative,
                fatal=False,
            )
        )
    return issues


def check_no_test_artifacts(names: list[str], index: dict[str, Any]) -> list[Issue]:
    issues = []
    candidates = list(names) + [f.get("path", "") for f in index.get("files", [])]
    for candidate in candidates:
        lowered = candidate.lower()
        for marker in DISALLOWED_TEST_MARKERS:
            if marker in lowered:
                issues.append(
                    _issue(
                        "artifact",
                        f"release artifact contains a test-only marker ({marker!r}) -- "
                        "test tooling must never ship in a release artifact",
                        path=candidate,
                    )
                )
    return issues


def check_manifest_index_agreement(manifest: dict[str, Any], index: dict[str, Any]) -> list[Issue]:
    issues = []
    resolved = {m["path"]: m for m in manifest.get("resolved_mods", []) if m.get("path")}
    indexed = {f["path"]: f for f in index.get("files", []) if f.get("path")}

    only_in_manifest = sorted(set(resolved) - set(indexed))
    only_in_index = sorted(set(indexed) - set(resolved))
    for path in only_in_manifest:
        issues.append(_issue("manifest", "present in manifest.json resolved_mods but missing from modrinth.index.json", path=path))
    for path in only_in_index:
        issues.append(_issue("manifest", "present in modrinth.index.json but missing from manifest.json resolved_mods", path=path))

    for path in set(resolved) & set(indexed):
        mod = resolved[path]
        file_entry = indexed[path]
        if mod.get("sha1") != file_entry.get("hashes", {}).get("sha1"):
            issues.append(_issue("manifest", "sha1 mismatch between manifest.json and modrinth.index.json", path=path))
        if mod.get("sha512") != file_entry.get("hashes", {}).get("sha512"):
            issues.append(_issue("manifest", "sha512 mismatch between manifest.json and modrinth.index.json", path=path))
        if mod.get("file_size") != file_entry.get("fileSize"):
            issues.append(_issue("manifest", "fileSize mismatch between manifest.json and modrinth.index.json", path=path))
        if mod.get("env") != file_entry.get("env"):
            issues.append(_issue("manifest", "env mismatch between manifest.json and modrinth.index.json", path=path))
    return issues


def collect_path_universe(artifact: LoadedArtifact) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Build the two structures shared by the path-safety and collision
    checks: {label: raw_path} for security scanning, and
    {normalized_installed_path: [labels]} for collision detection.
    """
    to_check: dict[str, str] = {}
    installed: dict[str, list[str]] = {}

    for name in artifact.names:
        if name in ("modrinth.index.json", "icon.png") or name.endswith("/"):
            continue
        to_check[f"zip-entry:{name}"] = name

    roots = _override_roots(artifact.names)
    for root, relatives in roots.items():
        for relative in relatives:
            installed.setdefault(relative, []).append(f"{root}:{relative}")

    if artifact.index:
        for file_entry in artifact.index.get("files", []):
            path = file_entry.get("path")
            if not isinstance(path, str):
                continue
            to_check[f"index:{path}"] = path
            installed.setdefault(path, []).append(f"index:{path}")

    return to_check, installed


def validate_archive(
    archive_path: Path,
    *,
    manifest: dict[str, Any] | None = None,
    expected_mc: str,
    expected_forge: str,
) -> list[Issue]:
    """Run every static (no-network) structural/security check against one
    built archive (.mrpack or the manual ZIP). Returns the full issue list;
    empty means the archive is clean.
    """
    artifact, issues = load_archive(archive_path)
    if artifact is None:
        return issues

    if artifact.index is not None:
        issues += check_format_and_game(artifact.index)
        issues += check_minecraft_and_forge_versions(
            artifact.index, expected_mc=expected_mc, expected_forge=expected_forge
        )
        issues += check_hash_and_size_syntax(artifact.index)
        issues += check_env_values(artifact.index)
        issues += check_download_urls(artifact.index)
        issues += check_override_collisions(artifact.names, artifact.index)
        issues += check_no_test_artifacts(artifact.names, artifact.index)
        if manifest is not None:
            issues += check_manifest_index_agreement(manifest, artifact.index)

    issues += check_override_layering(artifact.names)

    to_check, installed = collect_path_universe(artifact)
    issues += check_paths_security(to_check)
    issues += check_duplicate_and_case_collisions(installed)

    zip_entry_counts: dict[str, int] = {}
    for name in artifact.names:
        zip_entry_counts[name] = zip_entry_counts.get(name, 0) + 1
    for name, count in zip_entry_counts.items():
        if count > 1:
            issues.append(_issue("artifact", f"duplicate ZIP entry appears {count} times", path=name))

    artifact.zip_file.close()
    return issues


# --- Network-dependent checks (item 12/13: real downloads) ---------------


@dataclass
class DownloadVerification:
    path: str
    url: str
    ok: bool
    message: str
    final_host: str | None = None
    bytes_downloaded: int = 0


def _open_with_verified_redirects(url: str, *, max_redirects: int = 5, timeout: float = 60.0):
    current = url
    for _ in range(max_redirects + 1):
        parsed = urllib.parse.urlsplit(current)
        if parsed.scheme != "https":
            raise ValueError(f"refusing non-HTTPS URL during redirect chain: {current}")
        request = urllib.request.Request(current, headers={"User-Agent": USER_AGENT})
        opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler)
        try:
            response = urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 - https enforced above
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308) and exc.headers.get("Location"):
                current = urllib.parse.urljoin(current, exc.headers["Location"])
                continue
            raise
        return response, current
    raise ValueError(f"too many redirects (> {max_redirects}) starting from {url}")


def verify_declared_download(
    path: str,
    url: str,
    *,
    expected_sha1: str,
    expected_sha512: str,
    expected_size: int,
    cache_dir: Path | None = None,
    timeout: float = 120.0,
) -> DownloadVerification:
    """Actually fetch ``url`` (or reuse a content-addressed cache hit keyed
    by the expected sha512) and confirm real size/sha1/sha512 match the
    index. Domain allowlisting of the *declared* URL is handled separately
    by check_download_urls; this function additionally verifies the host
    reached after following redirects.
    """
    import hashlib

    origin_host = urllib.parse.urlsplit(url).hostname or ""
    cached_file = None
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached_file = cache_dir / f"{expected_sha512}.bin"

    if cached_file is not None and cached_file.exists():
        data_iter = cached_file.open("rb")
        final_host = origin_host
    else:
        try:
            response, final_url = _open_with_verified_redirects(url, timeout=timeout)
        except (urllib.error.URLError, ValueError, TimeoutError) as exc:
            return DownloadVerification(path=path, url=url, ok=False, message=f"download failed: {exc}")
        final_host = urllib.parse.urlsplit(final_url).hostname or ""
        allowed_targets = ALLOWED_REDIRECT_TARGET_SUFFIXES.get(origin_host, (origin_host,))
        if not any(final_host == suffix or final_host.endswith(suffix) for suffix in allowed_targets):
            response.close()
            return DownloadVerification(
                path=path,
                url=url,
                ok=False,
                message=f"redirected from {origin_host!r} to unexpected host {final_host!r}",
                final_host=final_host,
            )
        data_iter = response

    sha1 = hashlib.sha1()
    sha512 = hashlib.sha512()
    total = 0
    tmp_path = cached_file.with_suffix(".part") if cached_file else None
    sink = tmp_path.open("wb") if tmp_path else None
    try:
        while True:
            chunk = data_iter.read(1024 * 1024)
            if not chunk:
                break
            sha1.update(chunk)
            sha512.update(chunk)
            total += len(chunk)
            if sink:
                sink.write(chunk)
    finally:
        data_iter.close()
        if sink:
            sink.close()
    if tmp_path and cached_file:
        tmp_path.replace(cached_file)

    problems = []
    if total != expected_size:
        problems.append(f"size mismatch: expected {expected_size}, got {total}")
    if sha1.hexdigest().lower() != expected_sha1.lower():
        problems.append("sha1 mismatch")
    if sha512.hexdigest().lower() != expected_sha512.lower():
        problems.append("sha512 mismatch")

    if problems:
        return DownloadVerification(
            path=path, url=url, ok=False, message="; ".join(problems), final_host=final_host, bytes_downloaded=total
        )
    return DownloadVerification(
        path=path, url=url, ok=True, message="verified", final_host=final_host, bytes_downloaded=total
    )


def verify_all_downloads(
    index: dict[str, Any], *, cache_dir: Path | None = None, timeout: float = 120.0
) -> list[DownloadVerification]:
    results = []
    for file_entry in index.get("files", []):
        path = file_entry.get("path", "<missing path>")
        hashes = file_entry.get("hashes", {})
        downloads = file_entry.get("downloads") or [None]
        url = downloads[0]
        if not url:
            results.append(DownloadVerification(path=path, url="", ok=False, message="no download URL declared"))
            continue
        results.append(
            verify_declared_download(
                path,
                url,
                expected_sha1=hashes.get("sha1", ""),
                expected_sha512=hashes.get("sha512", ""),
                expected_size=file_entry.get("fileSize", -1),
                cache_dir=cache_dir,
                timeout=timeout,
            )
        )
    return results


def verify_sha256_sidecars(releases_dir: Path, sums_filename: str = "SHA256SUMS") -> list[Issue]:
    import hashlib

    sums_path = releases_dir / sums_filename
    if not sums_path.exists():
        return [_issue("checksum", f"{sums_path} does not exist")]
    issues: list[Issue] = []
    entries = []
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            issues.append(_issue("checksum", f"malformed SHA256SUMS line: {line!r}"))
            continue
        entries.append((parts[0], parts[1].strip()))

    if not entries:
        issues.append(_issue("checksum", "SHA256SUMS contains no entries"))

    for digest, filename in entries:
        if not re.match(r"^[0-9a-f]{64}$", digest):
            issues.append(_issue("checksum", f"invalid SHA-256 syntax for {filename}: {digest!r}"))
            continue
        artifact_path = releases_dir / filename
        if not artifact_path.exists():
            issues.append(_issue("checksum", f"SHA256SUMS references missing file: {filename}"))
            continue
        actual = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        if actual.lower() != digest.lower():
            issues.append(_issue("checksum", f"SHA-256 mismatch for {filename}: expected {digest}, got {actual}"))
    return issues
