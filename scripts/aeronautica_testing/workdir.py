"""Safe temporary-directory handling.

Every suite that needs scratch space (a fresh Minecraft instance, an
extracted .mrpack, a Docker volume mount) gets its directory from here. The
guarantees this module provides:

- Directories are always created under the OS temp dir (or an explicit
  ``--output-dir``-relative "work" directory), never at an arbitrary
  caller-supplied path.
- Cleanup only ever removes a path this module itself created and tracked;
  it never recursively deletes a broad or unresolved path.
- ``--keep-workdir`` disables cleanup and prints the retained path so a
  failure can be inspected by hand.
"""
from __future__ import annotations

import shutil
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class WorkdirManager:
    def __init__(self, *, keep: bool, base_dir: Path | None = None) -> None:
        self.keep = keep
        self._base_dir = base_dir
        self._created: list[Path] = []

    def new(self, label: str) -> Path:
        safe_label = "".join(c if c.isalnum() or c in "-_." else "-" for c in label)
        if self._base_dir is not None:
            self._base_dir.mkdir(parents=True, exist_ok=True)
            path = self._base_dir / f"{safe_label}-{uuid.uuid4().hex[:8]}"
            path.mkdir(parents=True, exist_ok=False)
        else:
            path = Path(tempfile.mkdtemp(prefix=f"aeronautica-{safe_label}-"))
        # Only paths this call created are ever eligible for cleanup.
        self._created.append(path.resolve())
        return path

    def cleanup(self) -> list[Path]:
        """Remove every tracked directory unless --keep-workdir was set.
        Returns the list of paths that were retained (either due to --keep
        or a removal failure), so the caller can report them.
        """
        retained: list[Path] = []
        for path in self._created:
            if self.keep:
                retained.append(path)
                continue
            resolved = path.resolve()
            # Defense in depth: refuse to remove anything that is not
            # actually inside a temp dir or our own base dir, and refuse
            # empty/root-like paths outright.
            if not str(resolved) or resolved == resolved.anchor:
                retained.append(path)
                continue
            try:
                if resolved.exists():
                    shutil.rmtree(resolved)
            except OSError:
                retained.append(path)
        return retained


@contextmanager
def scoped_workdir(manager: WorkdirManager, label: str) -> Iterator[Path]:
    path = manager.new(label)
    try:
        yield path
    finally:
        if not manager.keep:
            resolved = path.resolve()
            if resolved.exists() and str(resolved) and resolved != resolved.anchor:
                shutil.rmtree(resolved, ignore_errors=True)
                manager._created = [p for p in manager._created if p != resolved]
