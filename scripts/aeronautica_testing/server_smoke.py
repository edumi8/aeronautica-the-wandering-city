"""Phase 6: dedicated server smoke test using itzg/minecraft-server.

Boots the *actual local* .mrpack (never the published Modrinth project) in a
disposable container, verifies runtime versions from logs, drives RCON with
sentinel-based command verification (never trusting rcon-cli's exit code
alone), force-loads a chunk, exercises real registry IDs extracted from the
shipped jars (see tests/registry-facts.json /
scripts/aeronautica_testing/tools/extract_registry_facts.py), then stops,
restarts from the same data directory, and confirms persistence.

Image: itzg/minecraft-server:java17
  Pinned by tag; the exact digest resolved at pipeline-authoring time was:
  see IMAGE_DIGEST_NOTE below. Re-resolve with:
    docker pull itzg/minecraft-server:java17
    docker inspect --format='{{index .RepoDigests 0}}' itzg/minecraft-server:java17
Docs: https://docker-minecraft-server.readthedocs.io/
"""
from __future__ import annotations

import json
import re
import secrets
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import paths
from .proc import run as run_command

IMAGE = "itzg/minecraft-server:java17"
IMAGE_DIGEST_NOTE = (
    "Tag-pinned rather than digest-pinned: itzg republishes the `java17` tag on every image "
    "rebuild (base-image security patches), and the project intentionally tracks that tag. "
    "The pipeline resolves and logs the concrete digest at run time (see 'resolved image digest' "
    "evidence in the report) instead of hardcoding one that would go stale. "
    "Digest observed 2026-07-30: "
    "itzg/minecraft-server@sha256:5b3e96bcd7dace8ab7be89c245dc9ba0b1573fdef2f01d3e101ac40e7843fa70 "
    "-- re-resolve with `docker pull itzg/minecraft-server:java17 && "
    "docker inspect --format='{{index .RepoDigests 0}}' itzg/minecraft-server:java17`."
)

FATAL_LOG_SIGNATURES = (
    "ModLoadingException",
    "Failed to complete lifecycle event",
    "Failed to start the minecraft server",
    "Exception in server tick loop",
    "OutOfMemoryError",
    "Minecraft Crash Report",
)

# Intentionally narrow and documented -- see TESTING.md "why arbitrary ERROR
# log lines are not automatic failures". Only literal, known-benign lines
# belong here; never a broad regex that could swallow a real crash.
KNOWN_BENIGN_LOG_SUBSTRINGS: tuple[str, ...] = (
    "Advancement file does not exist",  # some KubeJS-touched datapacks probe optional advancements
)

DONE_PATTERN = re.compile(r"Done \([\d.]+s\)! For help, type \"help\"")


@dataclass
class ServerSmokeResult:
    ok: bool
    message: str
    evidence: list[str] = field(default_factory=list)


def _docker(args: list[str], *, timeout: float = 60, log_path: Path | None = None):
    return run_command(["docker", *args], timeout_seconds=timeout, log_path=log_path)


def resolve_image_digest() -> str | None:
    pull = _docker(["pull", IMAGE], timeout=600)
    if pull.returncode != 0:
        return None
    inspect = _docker(["inspect", "--format={{index .RepoDigests 0}}", IMAGE])
    if inspect.returncode == 0 and inspect.stdout_tail.strip():
        return inspect.stdout_tail.strip()
    return None


def container_name(suffix: str = "") -> str:
    return f"aeronautica-server-smoke-{suffix or uuid.uuid4().hex[:8]}"


def start_container(
    *,
    name: str,
    mrpack_path: Path,
    data_dir: Path,
    heap_mb: int = 5120,
    view_distance: int = 6,
    simulation_distance: int = 4,
    log_path: Path | None = None,
) -> "CommandResultLike":
    data_dir.mkdir(parents=True, exist_ok=True)
    mrpack_container_path = f"/modpacks/{mrpack_path.name}"
    env = {
        "EULA": "TRUE",
        "TYPE": "MODRINTH",
        "MODRINTH_MODPACK": mrpack_container_path,
        # Correctness test: the pack's own env.client/env.server metadata must
        # be right, so the image's built-in guess-work must not paper over it.
        "MODRINTH_DEFAULT_EXCLUDE_INCLUDES": "",
        "ONLINE_MODE": "FALSE",
        "MEMORY": f"{heap_mb}M",
        "VIEW_DISTANCE": str(view_distance),
        "SIMULATION_DISTANCE": str(simulation_distance),
        "ENABLE_RCON": "true",
        "RCON_PASSWORD": secrets.token_hex(8),
        "ENABLE_AUTOPAUSE": "false",
        "STOP_DURATION": "60",
    }
    args = ["run", "-d", "--name", name]
    for key, value in env.items():
        args += ["-e", f"{key}={value}"]
    args += [
        "-v",
        f"{mrpack_path.resolve()}:{mrpack_container_path}:ro",
        "-v",
        f"{data_dir.resolve()}:/data",
        IMAGE,
    ]
    return _docker(args, timeout=120, log_path=log_path)


def container_state(name: str) -> dict | None:
    result = _docker(["inspect", name])
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout_tail if result.stdout_tail.strip().startswith("[") else "[]")
    except json.JSONDecodeError:
        return None


def health_status(name: str) -> str:
    result = _docker(["inspect", "--format={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}", name])
    return result.stdout_tail.strip() if result.returncode == 0 else "unknown"


def is_running(name: str) -> bool:
    result = _docker(["inspect", "--format={{.State.Running}}", name])
    return result.returncode == 0 and result.stdout_tail.strip() == "true"


def logs(name: str, *, tail: int | None = None) -> str:
    args = ["logs"]
    if tail:
        args += ["--tail", str(tail)]
    args.append(name)
    result = _docker(args, timeout=30)
    return result.stdout_tail if result.stdout_path is None else result.stdout_path.read_text(encoding="utf-8", errors="replace")


def _full_logs(name: str, log_path: Path | None) -> str:
    result = _docker(["logs", name], timeout=30, log_path=log_path)
    if log_path and log_path.exists():
        return log_path.read_text(encoding="utf-8", errors="replace")
    return result.stdout_tail


def scan_for_fatal_errors(log_text: str) -> list[str]:
    return [sig for sig in FATAL_LOG_SIGNATURES if sig in log_text]


def container_started_at(name: str) -> str | None:
    result = _docker(["inspect", "--format={{.State.StartedAt}}", name])
    value = result.stdout_tail.strip()
    return value or None


def wait_for_healthy_or_done(
    name: str, *, timeout_seconds: float, log_path: Path | None = None, since: str | None = None
) -> ServerSmokeResult:
    """``since`` should be an RFC3339 timestamp (``container_started_at``)
    marking when *this* boot attempt began.

    Both a restart-persistence bug and a duplicate-"Done"-match bug were
    caught by a real run of this suite (2026-07-30) before this fix: right
    after ``docker start`` on a container that was previously healthy,
    Docker's cached health field can still read "healthy" for a moment
    before the new health check has run even once, and the unfiltered log
    history still contains the *previous* boot's "Done" line. Passing
    ``since`` scopes both the log scan and a short health-status debounce to
    genuinely new evidence from this boot attempt.
    """
    deadline = time.monotonic() + timeout_seconds
    minimum_wait_deadline = time.monotonic() + 5.0
    log_args = ["logs"]
    if since:
        log_args += ["--since", since]
    while time.monotonic() < deadline:
        if not is_running(name):
            _docker([*log_args, name], timeout=30, log_path=log_path)
            return ServerSmokeResult(False, "container exited before becoming healthy", [f"docker logs {name}"])
        result = _docker([*log_args, name], timeout=30, log_path=log_path)
        current_log = log_path.read_text(encoding="utf-8", errors="replace") if log_path and log_path.exists() else result.stdout_tail
        fatal = scan_for_fatal_errors(current_log)
        if fatal:
            return ServerSmokeResult(False, f"fatal signature(s) in logs: {fatal}", [str(log_path) if log_path else ""])
        status = health_status(name)
        ready = DONE_PATTERN.search(current_log) is not None
        if not ready and status == "healthy" and time.monotonic() >= minimum_wait_deadline:
            ready = True  # trust the health field only once it has had time to reflect *this* boot
        if ready:
            return ServerSmokeResult(True, f"server reported ready (health={status})", [])
        time.sleep(3)
    return ServerSmokeResult(False, f"timed out after {timeout_seconds}s waiting for health/Done", [str(log_path) if log_path else ""])


def rcon(name: str, command: str, *, timeout: float = 30) -> ServerSmokeResult:
    result = _docker(["exec", name, "rcon-cli", command], timeout=timeout)
    if result.returncode != 0:
        return ServerSmokeResult(False, f"rcon-cli exited {result.returncode}: {result.stdout_tail}")
    return ServerSmokeResult(True, result.stdout_tail)


_SCOREBOARD_GET_RE = re.compile(r"has (-?\d+)")


def ensure_scoreboard_objective(name: str, objective: str) -> None:
    rcon(name, f"scoreboard objectives add {objective} dummy")  # ignored if it already exists


def scoreboard_set(name: str, target: str, objective: str, value: int) -> ServerSmokeResult:
    return rcon(name, f"scoreboard players set {target} {objective} {value}")


def scoreboard_get(name: str, target: str, objective: str) -> tuple[bool, int | None, str]:
    """`/scoreboard players get` returns its value directly and
    synchronously through RCON, unlike `/say` nested inside `/execute run`
    -- confirmed unreliable (blank RCON response despite the broadcast
    genuinely reaching the server log a moment later) by a real run of this
    suite on 2026-07-30. Prefer this for any RCON-verified sentinel.
    """
    result = rcon(name, f"scoreboard players get {target} {objective}")
    if not result.ok:
        return False, None, result.message
    match = _SCOREBOARD_GET_RE.search(result.message)
    if not match:
        return False, None, result.message
    return True, int(match.group(1)), result.message


def rcon_verified(name: str, command: str, expect_substring: str, *, timeout: float = 30) -> ServerSmokeResult:
    """Never trust rcon-cli's exit code alone: require the expected sentinel
    text to appear in the actual Minecraft command response.
    """
    outcome = rcon(name, command, timeout=timeout)
    if not outcome.ok:
        return outcome
    if expect_substring not in outcome.message:
        return ServerSmokeResult(
            False,
            f"command {command!r} did not produce expected sentinel {expect_substring!r}; got: {outcome.message!r}",
        )
    return ServerSmokeResult(True, outcome.message)


def verify_java_version(name: str) -> ServerSmokeResult:
    result = _docker(["exec", name, "java", "-version"], timeout=20)
    text = result.stdout_tail
    ok = f'version "{paths.REQUIRED_JAVA_MAJOR}.' in text or f'version "{paths.REQUIRED_JAVA_MAJOR}"' in text
    return ServerSmokeResult(ok, text.strip().splitlines()[0] if text.strip() else "no output")


def verify_forge_layout(name: str, *, expected_mc: str, expected_forge: str) -> ServerSmokeResult:
    marker = f"{expected_mc}-{expected_forge}"
    result = _docker(["exec", name, "sh", "-c", "ls /data/libraries/net/minecraftforge/forge/ 2>/dev/null || true"], timeout=20)
    text = result.stdout_tail.strip()
    if marker in text:
        return ServerSmokeResult(True, f"found forge library directory {marker}")
    return ServerSmokeResult(False, f"expected forge library directory {marker!r}, found: {text!r}")


def stop_gracefully(name: str, *, timeout_seconds: float = 90, log_path: Path | None = None) -> ServerSmokeResult:
    rcon(name, "save-all flush", timeout=30)
    result = _docker(["stop", "--time", str(int(timeout_seconds)), name], timeout=timeout_seconds + 30, log_path=log_path)
    if result.returncode != 0:
        return ServerSmokeResult(False, f"docker stop failed: {result.stdout_tail}")
    if is_running(name):
        return ServerSmokeResult(False, "container still running after docker stop")
    return ServerSmokeResult(True, "stopped cleanly")


def remove_container(name: str) -> None:
    _docker(["rm", "-f", name], timeout=30)


def restart_existing_container(name: str, *, log_path: Path | None = None):
    """Starts an already-created (but stopped) container again, reusing its
    existing /data mount -- used by the persistence and worldgen-tool-
    injection flows so the second boot genuinely reuses prior state instead
    of a fresh `docker run`.
    """
    return _docker(["start", name], timeout=60, log_path=log_path)


def collect_evidence(name: str, evidence_dir: Path) -> list[str]:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    paths_written: list[str] = []

    full_log_path = evidence_dir / "container.log"
    _full_logs(name, full_log_path)
    paths_written.append(str(full_log_path))

    inspect_path = evidence_dir / "docker-inspect.json"
    inspect = _docker(["inspect", name])
    inspect_path.write_text(inspect.stdout_tail, encoding="utf-8")
    paths_written.append(str(inspect_path))

    return paths_written


def copy_data_logs(data_dir: Path, evidence_dir: Path) -> list[str]:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for candidate in ("logs/latest.log", "logs/debug.log"):
        source = data_dir / candidate
        if source.exists():
            destination = evidence_dir / Path(candidate).name
            shutil.copyfile(source, destination)
            written.append(str(destination))
    crash_dir = data_dir / "crash-reports"
    if crash_dir.exists():
        dest_dir = evidence_dir / "crash-reports"
        shutil.copytree(crash_dir, dest_dir, dirs_exist_ok=True)
        written.append(str(dest_dir))
    return written
