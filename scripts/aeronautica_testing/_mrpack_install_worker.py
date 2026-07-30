#!/usr/bin/env python3
"""Runs the third-party ``minecraft-launcher-lib`` .mrpack installer in a
subprocess so the pipeline's normal timeout/log-capture machinery
(:mod:`aeronautica_testing.proc`) governs it like every other external tool.

Deliberately independent of scripts/validate.py: this is Phase 4's
"do not validate the artifact only with the code that created it" -- it
must use someone else's installer implementation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path


def _hash_file(path: Path) -> dict[str, str]:
    sha1 = hashlib.sha1()
    sha512 = hashlib.sha512()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            sha1.update(chunk)
            sha512.update(chunk)
    return {"sha1": sha1.hexdigest(), "sha512": sha512.hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mrpack_path", type=Path)
    parser.add_argument("instance_dir", type=Path)
    parser.add_argument("--inventory-out", type=Path, required=True)
    parser.add_argument(
        "--skip-dependencies",
        action="store_true",
        help="Skip downloading vanilla Minecraft + Forge; only place mods/overrides. "
        "The client suite performs a full launchable install separately.",
    )
    args = parser.parse_args()

    try:
        import minecraft_launcher_lib.mrpack as mrpack
    except ImportError:
        print("minecraft-launcher-lib is not installed. Run: pip install -r tests/requirements.txt", file=sys.stderr)
        return 3

    with zipfile.ZipFile(args.mrpack_path) as zf:
        index = json.loads(zf.read("modrinth.index.json").decode("utf-8"))

    optional_files = [
        f["path"] for f in index.get("files", []) if (f.get("env") or {}).get("client") == "optional"
    ]

    args.instance_dir.mkdir(parents=True, exist_ok=True)
    parent_before = {p.name for p in args.instance_dir.parent.iterdir()} if args.instance_dir.parent.exists() else set()

    options: dict = {"optionalFiles": optional_files}
    if args.skip_dependencies:
        options["skipDependenciesInstall"] = True

    events: list[str] = []

    def _callback_factory(key: str):
        def _cb(value):
            events.append(f"{key}={value}")

        return _cb

    callback = {
        "setStatus": _callback_factory("status"),
        "setMax": _callback_factory("max"),
        "setProgress": _callback_factory("progress"),
    }

    mrpack.install_mrpack(
        str(args.mrpack_path),
        str(args.instance_dir),
        callback=callback,
        mrpack_install_options=options,
    )

    parent_after = {p.name for p in args.instance_dir.parent.iterdir()}
    escaped = sorted((parent_after - parent_before) - {args.instance_dir.name})

    inventory: dict[str, dict] = {}
    for path in sorted(args.instance_dir.rglob("*")):
        if path.is_file():
            relative = path.relative_to(args.instance_dir).as_posix()
            hashes = _hash_file(path)
            inventory[relative] = {"size": path.stat().st_size, **hashes}

    report = {
        "instance_dir": str(args.instance_dir),
        "optional_files_requested": optional_files,
        "escaped_parent_entries": escaped,
        "file_count": len(inventory),
        "files": inventory,
        "last_events": events[-10:],
    }
    args.inventory_out.parent.mkdir(parents=True, exist_ok=True)
    args.inventory_out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Installed {len(inventory)} files into {args.instance_dir}")
    if escaped:
        print(f"WARNING: unexpected sibling entries appeared next to the instance dir: {escaped}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:  # noqa: BLE001 - always report, never silent-success
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
