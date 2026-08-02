"""Phase 8: nightly/manual worldgen + performance capture.

Reuses the same Docker server plumbing as server_smoke.py, then injects two
test-only, pinned tools (never part of the release pack -- see
tests/worldgen/tools-lock.json) directly into the already-populated data
volume between a stop/start cycle, exactly like the persistence-check
pattern in Phase 6. This avoids guessing at itzg-image-specific
multi-source-pack env vars: the mounted /data/mods directory is ours to
manage directly once the Modrinth sync has run once.

Worldgen uses Chunky's standard admin commands (`chunky world/radius/center
/start/progress` -- see https://github.com/pop4959/Chunky/wiki/Commands,
and CHUNKY_DONE_RE's comment below for the real, live-verified RCON
response text). Performance uses
spark's plain-text `tps`/`health` commands only -- deliberately NOT the
`spark profiler` sampler, whose default output uploads to a public
bytebin-based viewer; this pipeline never uploads profiling data anywhere.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from . import paths
from .server_smoke import _docker, is_running, rcon  # noqa: SLF001 - intentional reuse within the package

TOOLS_LOCK_PATH = paths.WORLDGEN_DIR / "tools-lock.json"

# Both the wording and the correct command were wrong before this comment
# existed -- confirmed by two real, live runs against a real dedicated
# server (2026-07-30): `chunky query` is rejected outright ("Incorrect
# argument for command"; the real command is `chunky progress`, per
# https://github.com/pop4959/Chunky/wiki/Commands), and even after fixing
# that, Chunky's real idle/done response is "[Chunky] No tasks running."
# -- never any of "Completed"/"Chunky finished"/"Task finished", which
# never appeared in real output and would have polled until timeout on
# every run, exactly as the first real worldgen suite execution did
# (worldgen:generate-radius-50 timed out at the 5400s cap with that
# original regex). `chunky start`'s own response was also verified live:
# "[Chunky] Task started in <world> for the square region centered at
# <x>, <z> with radius <r>."
CHUNKY_START_CONFIRMED_RE = re.compile(r"task started", re.IGNORECASE)
CHUNKY_DONE_RE = re.compile(r"no tasks running", re.IGNORECASE)


@dataclass
class WorldgenOutcome:
    ok: bool
    message: str
    chunks_processed: int | None = None
    duration_seconds: float | None = None
    evidence: list[str] | None = None


def load_tools_lock() -> dict:
    return json.loads(TOOLS_LOCK_PATH.read_text(encoding="utf-8"))


def download_tool(tool: dict, cache_dir: Path) -> Path:
    import hashlib
    import urllib.request

    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / tool["filename"]
    if dest.exists() and dest.stat().st_size == tool["file_size"]:
        return dest
    request = urllib.request.Request(tool["download_url"], headers={"User-Agent": "Aeronautica-Wandering-City-TestPipeline/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response, dest.open("wb") as out:
        out.write(response.read())
    digest = hashlib.sha512(dest.read_bytes()).hexdigest()
    if digest.lower() != tool["sha512"].lower():
        dest.unlink(missing_ok=True)
        raise RuntimeError(f"sha512 mismatch downloading {tool['filename']}")
    return dest


def inject_test_tools(data_dir: Path, cache_dir: Path) -> list[str]:
    """Copy Chunky + spark jars directly onto the host-mounted data volume.
    Must only be called between a stop and the next start -- see module
    docstring for why this avoids the modrinth-sync-on-boot race.
    """
    lock = load_tools_lock()
    mods_dir = data_dir / "mods"
    mods_dir.mkdir(parents=True, exist_ok=True)
    placed = []
    for tool in lock["tools"].values():
        source = download_tool(tool, cache_dir)
        dest = mods_dir / source.name
        dest.write_bytes(source.read_bytes())
        placed.append(str(dest))
    return placed


def remove_test_tools(data_dir: Path) -> None:
    lock = load_tools_lock()
    mods_dir = data_dir / "mods"
    for tool in lock["tools"].values():
        candidate = mods_dir / tool["filename"]
        candidate.unlink(missing_ok=True)


def run_worldgen(
    container: str,
    *,
    dimension: str = "minecraft:overworld",
    radius: int,
    center: tuple[int, int] = (0, 0),
    timeout_seconds: float,
    poll_interval: float = 10.0,
) -> WorldgenOutcome:
    started = time.monotonic()

    world_result = rcon(container, f"chunky world {dimension}")
    if not world_result.ok:
        return WorldgenOutcome(False, f"chunky world failed: {world_result.message}")

    center_result = rcon(container, f"chunky center {center[0]} {center[1]}")
    if not center_result.ok:
        return WorldgenOutcome(False, f"chunky center failed: {center_result.message}")

    radius_result = rcon(container, f"chunky radius {radius}")
    if not radius_result.ok:
        return WorldgenOutcome(False, f"chunky radius failed: {radius_result.message}")

    start_result = rcon(container, "chunky start")
    if not start_result.ok or not CHUNKY_START_CONFIRMED_RE.search(start_result.message):
        return WorldgenOutcome(False, f"chunky start did not confirm a task began: {start_result.message!r}")

    last_status = ""
    last_progress_status = ""  # last reading *before* completion, for the best-effort chunk count below
    while time.monotonic() - started < timeout_seconds:
        if not is_running(container):
            return WorldgenOutcome(False, "server container exited during worldgen", duration_seconds=time.monotonic() - started)
        progress = rcon(container, "chunky progress")
        last_status = progress.message or last_status
        if CHUNKY_DONE_RE.search(last_status):
            break
        last_progress_status = last_status
        time.sleep(poll_interval)
    else:
        return WorldgenOutcome(
            False,
            f"worldgen did not report completion within {timeout_seconds}s; last status: {last_status!r}",
            duration_seconds=time.monotonic() - started,
        )

    duration = time.monotonic() - started
    # Best-effort only: Chunky's confirmed-real "No tasks running" done
    # message carries no chunk count, so this can only ever come from an
    # in-progress reading (if the task ran long enough for one) -- None is
    # the honest answer when it doesn't, not a fabricated count.
    chunks_match = re.search(r"(\d+)\s+chunk", last_progress_status)
    chunks = int(chunks_match.group(1)) if chunks_match else None
    return WorldgenOutcome(True, f"worldgen completed: {last_status}", chunks_processed=chunks, duration_seconds=duration)


def capture_performance_snapshot(container: str, evidence_dir: Path, *, warmup_seconds: float = 30.0) -> WorldgenOutcome:
    """Warms up, then captures plain-text tps/health output as local
    evidence. Never invokes the spark sampler/profiler (that uploads to a
    public viewer by default) -- see module docstring.
    """
    time.sleep(warmup_seconds)
    evidence_dir.mkdir(parents=True, exist_ok=True)

    tps = rcon(container, "spark tps")
    health = rcon(container, "spark health")

    snapshot_path = evidence_dir / "spark-snapshot.txt"
    snapshot_path.write_text(
        f"=== spark tps ===\n{tps.message}\n\n=== spark health ===\n{health.message}\n",
        encoding="utf-8",
    )

    if not tps.ok and not health.ok:
        return WorldgenOutcome(False, "both spark tps and spark health failed", evidence=[str(snapshot_path)])
    return WorldgenOutcome(True, "captured local performance snapshot", evidence=[str(snapshot_path)])
