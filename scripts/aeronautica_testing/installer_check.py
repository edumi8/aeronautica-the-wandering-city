"""Phase 4: independent clean installation using minecraft-launcher-lib.

Runs the pinned third-party .mrpack installer (never our own build code)
against the actual built artifact, then compares the resulting file tree to
what modrinth.index.json + overrides declare.
"""
from __future__ import annotations

import json
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import paths
from .mrpack_validate import Issue
from .proc import CommandResult, run as run_command

WORKER_SCRIPT = Path(__file__).resolve().parent / "_mrpack_install_worker.py"


@dataclass
class InstallCheckOutcome:
    command_result: CommandResult
    inventory: dict | None = None
    issues: list[Issue] = field(default_factory=list)


def run_installer(
    *,
    mrpack_path: Path,
    instance_dir: Path,
    inventory_path: Path,
    timeout_seconds: float = 900,
    log_path: Path | None = None,
    skip_dependencies: bool = True,
) -> InstallCheckOutcome:
    command = [
        sys.executable,
        str(WORKER_SCRIPT),
        str(mrpack_path),
        str(instance_dir),
        "--inventory-out",
        str(inventory_path),
    ]
    if skip_dependencies:
        command.append("--skip-dependencies")

    result = run_command(command, cwd=paths.ROOT, timeout_seconds=timeout_seconds, log_path=log_path)
    outcome = InstallCheckOutcome(command_result=result)

    if result.timed_out:
        outcome.issues.append(Issue(category="installer", message=f"installer worker timed out after {timeout_seconds}s"))
        return outcome
    if result.returncode != 0:
        outcome.issues.append(
            Issue(category="installer", message=f"installer worker exited {result.returncode}: {result.stdout_tail}")
        )
        return outcome

    if not inventory_path.exists():
        outcome.issues.append(Issue(category="installer", message="installer worker did not produce an inventory file"))
        return outcome

    outcome.inventory = json.loads(inventory_path.read_text(encoding="utf-8"))

    if outcome.inventory.get("escaped_parent_entries"):
        outcome.issues.append(
            Issue(
                category="installer",
                message="installer wrote sibling entries outside the instance directory: "
                f"{outcome.inventory['escaped_parent_entries']}",
            )
        )
    return outcome


def compare_inventory(
    inventory: dict, *, mrpack_path: Path, index: dict
) -> list[Issue]:
    issues: list[Issue] = []
    installed_files: dict[str, dict] = inventory.get("files", {})

    expected_mod_paths = {
        f["path"]
        for f in index.get("files", [])
        if (f.get("env") or {}).get("client", "required") in ("required", "optional")
    }
    unsupported_mod_paths = {
        f["path"] for f in index.get("files", []) if (f.get("env") or {}).get("client") == "unsupported"
    }

    with zipfile.ZipFile(mrpack_path) as zf:
        names = zf.namelist()
        expected_override_paths: dict[str, bytes] = {}
        for name in names:
            for root in ("overrides/", "client-overrides/"):
                if name.startswith(root) and not name.endswith("/"):
                    relative = name[len(root) :]
                    expected_override_paths[relative] = zf.read(name)

    missing = sorted((expected_mod_paths | set(expected_override_paths)) - set(installed_files))
    for path in missing:
        issues.append(Issue(category="installer", message="expected file was not installed", path=path))

    unexpected_present = sorted(unsupported_mod_paths & set(installed_files))
    for path in unexpected_present:
        issues.append(
            Issue(
                category="installer",
                message="file marked env.client=unsupported was installed anyway",
                path=path,
            )
        )

    for file_entry in index.get("files", []):
        path = file_entry["path"]
        if path not in installed_files or path not in expected_mod_paths:
            continue
        installed = installed_files[path]
        declared = file_entry.get("hashes", {})
        if installed.get("sha1", "").lower() != (declared.get("sha1") or "").lower():
            issues.append(Issue(category="checksum", message="installed file sha1 does not match modrinth.index.json", path=path))
        if installed.get("sha512", "").lower() != (declared.get("sha512") or "").lower():
            issues.append(Issue(category="checksum", message="installed file sha512 does not match modrinth.index.json", path=path))
        if installed.get("size") != file_entry.get("fileSize"):
            issues.append(
                Issue(
                    category="artifact",
                    message=f"installed file size {installed.get('size')} != declared fileSize {file_entry.get('fileSize')}",
                    path=path,
                )
            )

    import hashlib

    for relative, expected_bytes in expected_override_paths.items():
        installed = installed_files.get(relative)
        if installed is None:
            continue  # already reported as missing above
        expected_sha1 = hashlib.sha1(expected_bytes).hexdigest()
        if installed.get("sha1", "").lower() != expected_sha1.lower():
            issues.append(
                Issue(category="installer", message="installed override content does not match the archived override", path=relative)
            )

    return issues
