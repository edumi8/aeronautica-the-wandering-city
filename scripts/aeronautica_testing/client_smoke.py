"""Phase 5: real Forge client smoke test.

Built on minecraft-launcher-lib. It launches the complete pack against a
real Xvfb/Mesa OpenGL context and waits for ModernFix's positive marker that
Minecraft has completed startup.

Critical constraint: the test must not silently resolve a different Forge
build. This module therefore:

  1. Installs the *exact* `1.20.1-47.4.10` client profile itself, using
     Forge's own official installer jar in headless `--installClient` mode
     (this is literally what Forge's installer supports, and is the
     mechanism ForgeGradle itself relies on -- verified locally before
     writing this module, see IMAGE/VERSION notes below).
  2. Verifies the resulting version JSON's id/inheritsFrom/`--fml.forgeVersion`
     match 1.20.1 / 47.4.10 *before* ever launching.
  3. Launches that already-installed version by exact id
     (`1.20.1-forge-47.4.10`), so there is no ambiguity about what gets
     tested.

Requires a Linux environment with Xvfb + software OpenGL (native on a Linux
CI runner, or via docker/client-test.Dockerfile everywhere else -- see
prereqs.detect_xvfb / TESTING.md).
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import paths
from .installer_check import WORKER_SCRIPT

MC_VERSION = paths.MC_VERSION
FORGE_VERSION = paths.FORGE_VERSION
FORGE_VERSION_ID = f"{MC_VERSION}-forge-{FORGE_VERSION}"

FORGE_INSTALLER_URL = (
    f"https://maven.minecraftforge.net/net/minecraftforge/forge/"
    f"{MC_VERSION}-{FORGE_VERSION}/forge-{MC_VERSION}-{FORGE_VERSION}-installer.jar"
)

USER_AGENT = "Aeronautica-Wandering-City-TestPipeline/1.0 (+client-smoke-test)"

FATAL_LOG_SIGNATURES = (
    "ModLoadingException",
    "Failed to complete lifecycle event",
    "Minecraft Crash Report",
    "OutOfMemoryError",
    "LWJGL Exception",
)

CLIENT_SUCCESS_SIGNATURE = "Game took "

MINIMAL_LAUNCHER_PROFILES = json.dumps(
    {"profiles": {}, "selectedProfile": "(Default)", "clientToken": "0", "authenticationDatabase": {}}
)


@dataclass
class StepOutcome:
    ok: bool
    message: str
    evidence: list[str] = field(default_factory=list)


def _download(url: str, dest: Path, *, timeout: float = 300) -> StepOutcome:
    if dest.exists() and dest.stat().st_size > 0:
        return StepOutcome(True, f"cached: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, tmp.open("wb") as out:
            while chunk := response.read(1024 * 1024):
                out.write(chunk)
    except (urllib.error.URLError, TimeoutError) as exc:  # noqa: F821 - urllib.error imported below
        return StepOutcome(False, f"download failed: {url} -> {exc}")
    tmp.replace(dest)
    return StepOutcome(True, f"downloaded {dest.stat().st_size} bytes -> {dest}")


import urllib.error  # noqa: E402 - grouped near use for readability of the try/except above


def install_forge_client(gamedir: Path, cache_dir: Path, *, timeout_seconds: float = 900, log_path: Path | None = None) -> StepOutcome:
    gamedir.mkdir(parents=True, exist_ok=True)
    (gamedir / "launcher_profiles.json").write_text(MINIMAL_LAUNCHER_PROFILES, encoding="utf-8")
    # Avoid unattended first-run accessibility/pause screens in Xvfb.
    (gamedir / "options.txt").write_text(
        "onboardAccessibility:false\npauseOnLostFocus:false\n",
        encoding="utf-8",
    )

    # Forge's installer does not install the vanilla parent metadata/assets
    # expected by a normal launcher. Install the pinned vanilla version first
    # through minecraft-launcher-lib, which is already a locked test
    # dependency and uses Mojang's official manifests.
    try:
        import minecraft_launcher_lib

        minecraft_launcher_lib.install.install_minecraft_version(MC_VERSION, str(gamedir))
    except Exception as exc:  # noqa: BLE001 - convert dependency errors into evidence
        return StepOutcome(False, f"vanilla client installation failed: {exc}")

    installer_path = cache_dir / f"forge-{MC_VERSION}-{FORGE_VERSION}-installer.jar"
    download = _download(FORGE_INSTALLER_URL, installer_path)
    if not download.ok:
        return download

    try:
        result = subprocess.run(
            ["java", "-jar", str(installer_path), "--installClient", str(gamedir)],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        partial = ((exc.stdout or "") + (exc.stderr or "")) if isinstance(exc.stdout, str) else ""
        if log_path:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(partial, encoding="utf-8")
        return StepOutcome(
            False,
            f"forge installer did not finish within {timeout_seconds}s (treated as a hang, not a hard crash -- "
            "class-patching across the whole vanilla jar is CPU-bound and can be slow on a loaded machine)",
            [str(log_path)] if log_path else [],
        )
    output = (result.stdout or "") + (result.stderr or "")
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(output, encoding="utf-8")
    if result.returncode != 0 or "Successfully installed client" not in output:
        return StepOutcome(False, f"forge installer exited {result.returncode}: {output[-800:]}", [str(log_path)] if log_path else [])
    return StepOutcome(True, "forge client installed", [str(log_path)] if log_path else [])


def verify_installed_forge_version(gamedir: Path) -> StepOutcome:
    version_json_path = gamedir / "versions" / FORGE_VERSION_ID / f"{FORGE_VERSION_ID}.json"
    if not version_json_path.exists():
        return StepOutcome(False, f"expected version file missing: {version_json_path}")
    data = json.loads(version_json_path.read_text(encoding="utf-8"))
    if data.get("id") != FORGE_VERSION_ID:
        return StepOutcome(False, f"version id mismatch: expected {FORGE_VERSION_ID}, got {data.get('id')!r}")
    if data.get("inheritsFrom") != MC_VERSION:
        return StepOutcome(False, f"inheritsFrom mismatch: expected {MC_VERSION}, got {data.get('inheritsFrom')!r}")
    game_args = data.get("arguments", {}).get("game", [])
    args_text = " ".join(str(a) for a in game_args)
    if f"--fml.forgeVersion {FORGE_VERSION}" not in args_text and FORGE_VERSION not in args_text:
        return StepOutcome(False, f"installed version JSON does not declare forgeVersion {FORGE_VERSION}: {args_text[:300]}")
    return StepOutcome(True, f"verified installed version id={data['id']} inheritsFrom={data['inheritsFrom']}", [str(version_json_path)])


def stage_pack_mods(mrpack_path: Path, gamedir: Path, *, timeout_seconds: float = 900, log_path: Path | None = None) -> StepOutcome:
    inventory_path = gamedir / ".aeronautica-install-inventory.json"
    result = subprocess.run(
        [sys.executable, str(WORKER_SCRIPT), str(mrpack_path), str(gamedir), "--inventory-out", str(inventory_path), "--skip-dependencies"],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        encoding="utf-8",
        errors="replace",
    )
    output = (result.stdout or "") + (result.stderr or "")
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(output, encoding="utf-8")
    if result.returncode != 0:
        return StepOutcome(False, f"mod staging failed: {output[-800:]}", [str(log_path)] if log_path else [])
    return StepOutcome(True, "pack mods + overrides staged", [str(log_path)] if log_path else [])


def _pump_stdout_to_queue(stream, sink: "queue.Queue[str | None]") -> None:
    try:
        for line in iter(stream.readline, ""):
            sink.put(line)
    finally:
        sink.put(None)  # sentinel: stream closed / process exited


def run_client_session(
    gamedir: Path,
    *,
    timeout_seconds: float,
    log_path: Path,
    offline_username: str = "AeronauticaTester",
) -> StepOutcome:
    """Launch the exact installed Forge client and wait for full startup.

    minecraft-launcher-lib builds the standard Mojang/Forge command. This is
    intentionally not launched through HeadlessMC: its offline mode forces
    no-context LWJGL instrumentation, which is incompatible with Embeddium's
    valid OpenGL fence usage. CI supplies Xvfb + Mesa for a real GL context.
    """
    import queue
    import threading

    # minecraft-launcher-lib embeds the supplied directory into classpath
    # entries. Resolve it before changing the subprocess cwd, otherwise a
    # relative test-results/... path is interpreted again from inside the
    # gamedir and every Forge library becomes invisible.
    gamedir = gamedir.resolve()
    env = dict(os.environ)
    env.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")

    try:
        import minecraft_launcher_lib

        options = minecraft_launcher_lib.utils.generate_test_options()
        options.update(
            {
                "username": offline_username,
                "executablePath": "java",
                "gameDirectory": str(gamedir),
                "launcherName": "AeronauticaTestPipeline",
                "launcherVersion": "1.0",
                "jvmArguments": ["-Xmx4G"],
            }
        )
        command = minecraft_launcher_lib.command.get_minecraft_command(
            FORGE_VERSION_ID, str(gamedir), options
        )
    except Exception as exc:  # noqa: BLE001 - report command construction cleanly
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(str(exc), encoding="utf-8")
        return StepOutcome(False, f"could not construct Forge client command: {exc}", [str(log_path)])

    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()

    try:
        process = subprocess.Popen(
            command,
            cwd=str(gamedir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
    except FileNotFoundError as exc:
        return StepOutcome(False, f"could not launch Forge client: {exc}")

    output_lines: list[str] = []
    assert process.stdout is not None
    line_queue: "queue.Queue[str | None]" = queue.Queue()
    reader = threading.Thread(target=_pump_stdout_to_queue, args=(process.stdout, line_queue), daemon=True)
    reader.start()

    stream_closed = False

    try:
        while True:
            remaining = timeout_seconds - (time.monotonic() - started)
            if remaining <= 0:
                break
            if stream_closed and process.poll() is not None:
                break
            try:
                line = line_queue.get(timeout=min(remaining, 1.0))
            except queue.Empty:
                continue
            if line is None:
                stream_closed = True
                continue
            output_lines.append(line.rstrip("\n"))
            if any(sig in line for sig in FATAL_LOG_SIGNATURES) or CLIENT_SUCCESS_SIGNATURE in line:
                break
    finally:
        full_output = "\n".join(output_lines)
        log_path.write_text(full_output, encoding="utf-8")

        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=15)
            except Exception:
                process.kill()
                process.wait(timeout=15)

    duration = time.monotonic() - started
    fatal_hits = [sig for sig in FATAL_LOG_SIGNATURES if sig in full_output]
    if fatal_hits:
        return StepOutcome(False, f"fatal signature(s) in client log: {fatal_hits}", [str(log_path)])
    if duration >= timeout_seconds:
        return StepOutcome(False, f"client session did not exit within {timeout_seconds}s (treated as hang)", [str(log_path)])
    if CLIENT_SUCCESS_SIGNATURE not in full_output:
        return StepOutcome(
            False,
            "client exited without the positive full-startup "
            f"marker {CLIENT_SUCCESS_SIGNATURE!r}",
            [str(log_path)],
        )
    return StepOutcome(
        True,
        f"Forge client completed Forge/mod/resource/OpenGL startup "
        f"({CLIENT_SUCCESS_SIGNATURE!r}, duration={duration:.1f}s)",
        [str(log_path)],
    )


def capture_screenshot(evidence_dir: Path, display: str = ":99") -> str | None:
    if platform.system() != "Linux":
        return None
    evidence_dir.mkdir(parents=True, exist_ok=True)
    xwd_path = evidence_dir / "display.xwd"
    png_path = evidence_dir / "display.png"
    env = dict(os.environ)
    env["DISPLAY"] = display
    try:
        subprocess.run(["xwd", "-root", "-out", str(xwd_path)], env=env, timeout=15, capture_output=True)
        subprocess.run(["convert", str(xwd_path), str(png_path)], timeout=15, capture_output=True)
    except (subprocess.TimeoutExpired, OSError):
        return None
    return str(png_path) if png_path.exists() else None


def collect_failure_evidence(gamedir: Path, evidence_dir: Path) -> list[str]:
    import shutil

    evidence_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for candidate in ("logs/latest.log", "logs/debug.log"):
        source = gamedir / candidate
        if source.exists():
            dest = evidence_dir / Path(candidate).name
            shutil.copyfile(source, dest)
            written.append(str(dest))
    crash_dir = gamedir / "crash-reports"
    if crash_dir.exists():
        dest_dir = evidence_dir / "crash-reports"
        shutil.copytree(crash_dir, dest_dir, dirs_exist_ok=True)
        written.append(str(dest_dir))
    screenshot = capture_screenshot(evidence_dir)
    if screenshot:
        written.append(screenshot)
    return written
