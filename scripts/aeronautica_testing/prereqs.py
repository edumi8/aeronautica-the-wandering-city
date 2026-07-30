"""Prerequisite detection shared by the standalone ``prereqs`` command and by
every suite's own preflight check.

Design: each :class:`Prereq` records what was detected, what is required,
whether it is satisfied, and (if not) exact remediation instructions. Only
``python`` and ``java`` are ``mandatory`` (nothing else can run without
them); everything else is tagged with which suites need it, so a developer
without Docker can still run ``fast`` all day without the report screaming
at them, while ``server``/``worldgen`` will refuse to silently skip.

Nothing here installs software or requires administrator access; nothing is
run without printing why.
"""
from __future__ import annotations

import ctypes
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from . import paths

MIN_DISK_GB = 10.0
MIN_MEMORY_GB = 8.0
MIN_PYTHON = (3, 11)
USER_AGENT = "Aeronautica-Wandering-City-TestPipeline/1.0 (+prereqs)"


@dataclass
class Prereq:
    name: str
    detected: str | None
    required: str
    ok: bool
    remediation: str
    required_for: tuple[str, ...] = field(default_factory=tuple)
    mandatory: bool = False

    @property
    def status_word(self) -> str:
        if self.ok:
            return "ok"
        return "missing" if self.mandatory else "warning"


def _run(cmd: list[str], timeout: float = 15.0) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return completed.returncode, (completed.stdout or "") + (completed.stderr or "")
    except FileNotFoundError:
        return 127, ""
    except subprocess.TimeoutExpired:
        return 124, "timed out"
    except OSError as exc:
        return 1, str(exc)


def detect_python() -> Prereq:
    version = sys.version_info
    ok = (version.major, version.minor) >= MIN_PYTHON
    return Prereq(
        name="python",
        detected=f"{platform.python_version()} ({sys.executable})",
        required=f">={MIN_PYTHON[0]}.{MIN_PYTHON[1]}",
        ok=ok,
        remediation="Install Python 3.11+ from https://www.python.org/downloads/ and ensure it is on PATH.",
        required_for=("prereqs", "fast", "artifact", "client", "server", "gametest", "worldgen", "full"),
        mandatory=True,
    )


_JAVA_VERSION_RE = re.compile(r'version "(\d+)(?:\.(\d+))?')


def detect_java() -> Prereq:
    java = shutil.which("java")
    if not java:
        return Prereq(
            name="java",
            detected=None,
            required=f"Java {paths.REQUIRED_JAVA_MAJOR} (exact major version)",
            ok=False,
            remediation=(
                "Install Eclipse Temurin 17 from https://adoptium.net/temurin/releases/?version=17 "
                "and ensure 'java' resolves to it on PATH (or set JAVA_HOME)."
            ),
            required_for=("client", "gametest"),
            mandatory=True,
        )
    code, output = _run([java, "-version"])
    match = _JAVA_VERSION_RE.search(output)
    major = None
    if match:
        first, second = match.group(1), match.group(2)
        # Old scheme: "1.8.0_xxx" -> major 8. Modern scheme: "17.0.16" -> major 17.
        major = int(second) if first == "1" and second else int(first)
    ok = code == 0 and major == paths.REQUIRED_JAVA_MAJOR
    detected = output.splitlines()[0].strip() if output.strip() else f"java at {java} (version string unreadable)"
    return Prereq(
        name="java",
        detected=detected,
        required=f"Java {paths.REQUIRED_JAVA_MAJOR} (exact major version) -- release-gating per README",
        ok=ok,
        remediation=(
            f"Detected major version {major}. Install/select Eclipse Temurin 17 "
            "(https://adoptium.net/temurin/releases/?version=17); on multi-JDK machines "
            "point JAVA_HOME and PATH at the Java 17 install."
        ),
        required_for=("client", "gametest"),
        mandatory=True,
    )


def detect_docker() -> Prereq:
    docker = shutil.which("docker")
    if not docker:
        return Prereq(
            name="docker",
            detected=None,
            required="Docker Engine/Desktop with a reachable daemon",
            ok=False,
            remediation="Install Docker Desktop (https://www.docker.com/products/docker-desktop/) and start it.",
            required_for=("server", "worldgen"),
        )
    code, output = _run([docker, "info"], timeout=20.0)
    ok = code == 0
    version_code, version_out = _run([docker, "--version"])
    detected = version_out.strip() or "docker present"
    return Prereq(
        name="docker",
        detected=detected,
        required="Docker Engine/Desktop with a reachable daemon",
        ok=ok,
        remediation=(
            "Docker CLI found but the daemon is not reachable. Start Docker Desktop "
            "(or `sudo systemctl start docker` on Linux) and retry."
        ),
        required_for=("server", "worldgen"),
    )


def detect_powershell() -> Prereq:
    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    detected = None
    if pwsh:
        _, out = _run([pwsh, "-NoLogo", "-NoProfile", "-Command", "$PSVersionTable.PSVersion.ToString()"])
        detected = f"{pwsh} ({out.strip().splitlines()[-1] if out.strip() else 'version unknown'})"
    return Prereq(
        name="powershell",
        detected=detected,
        required="PowerShell 5.1+ or PowerShell 7+ (pwsh)",
        ok=pwsh is not None,
        remediation="Install PowerShell 7 from https://github.com/PowerShell/PowerShell/releases (optional on Linux/macOS).",
        required_for=("test.ps1 wrapper",),
    )


def detect_bash() -> Prereq:
    bash = shutil.which("bash")
    return Prereq(
        name="bash",
        detected=bash,
        required="bash (Git Bash / WSL / native)",
        ok=bash is not None,
        remediation="On Windows install Git for Windows (provides Git Bash) or use WSL.",
        required_for=("test.sh wrapper",),
    )


def detect_wsl() -> Prereq:
    if platform.system() != "Windows":
        return Prereq(
            name="wsl",
            detected="n/a (not Windows)",
            required="WSL2 with a Linux distro (Windows only, used for the headless client route)",
            ok=True,
            remediation="",
            required_for=("client (Windows only)",),
        )
    wsl = shutil.which("wsl")
    if not wsl:
        return Prereq(
            name="wsl",
            detected=None,
            required="WSL2 with a Linux distro",
            ok=False,
            remediation="Install WSL2: `wsl --install` from an elevated PowerShell, then restart.",
            required_for=("client (Windows only)",),
        )
    code, out = _run([wsl, "-l", "-v"], timeout=20.0)
    has_distro = code == 0 and any(line.strip() for line in out.splitlines()[1:])
    return Prereq(
        name="wsl",
        detected=out.strip().replace("\x00", "") if out.strip() else "wsl.exe present",
        required="WSL2 with at least one installed Linux distro",
        ok=has_distro,
        remediation="Install a distro: `wsl --install -d Ubuntu`. Docker Desktop is used instead when available.",
        required_for=("client (Windows only, fallback route)",),
    )


def detect_xvfb() -> Prereq:
    if platform.system() != "Linux":
        return Prereq(
            name="xvfb",
            detected="n/a (not Linux)",
            required="Xvfb + software OpenGL (Linux only; Docker/WSL provide a Linux runtime otherwise)",
            ok=True,
            remediation="",
            required_for=("client (native Linux route)",),
        )
    xvfb_run = shutil.which("xvfb-run")
    return Prereq(
        name="xvfb",
        detected=xvfb_run,
        required="xvfb-run on PATH, Mesa software rendering (llvmpipe) recommended",
        ok=xvfb_run is not None,
        remediation="Debian/Ubuntu: `sudo apt-get install -y xvfb mesa-utils libgl1-mesa-dri`.",
        required_for=("client (native Linux route)",),
    )


def detect_disk_space(target: os.PathLike | str = paths.ROOT) -> Prereq:
    usage = shutil.disk_usage(target)
    free_gb = usage.free / (1024**3)
    ok = free_gb >= MIN_DISK_GB
    return Prereq(
        name="disk-space",
        detected=f"{free_gb:.1f} GB free at {target}",
        required=f">={MIN_DISK_GB:.0f} GB free",
        ok=ok,
        remediation="Free up disk space: artifact downloads, Docker images, and Gradle/ForgeGradle caches need headroom.",
        required_for=("artifact", "client", "server", "gametest", "worldgen", "full"),
    )


def _total_memory_gb() -> float | None:
    system = platform.system()
    try:
        if system == "Linux":
            with open("/proc/meminfo", encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("MemTotal:"):
                        kib = int(line.split()[1])
                        return kib / (1024**2)
        elif system == "Windows":
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_uint32),
                    ("dwMemoryLoad", ctypes.c_uint32),
                    ("ullTotalPhys", ctypes.c_uint64),
                    ("ullAvailPhys", ctypes.c_uint64),
                    ("ullTotalPageFile", ctypes.c_uint64),
                    ("ullAvailPageFile", ctypes.c_uint64),
                    ("ullTotalVirtual", ctypes.c_uint64),
                    ("ullAvailVirtual", ctypes.c_uint64),
                    ("ullAvailExtendedVirtual", ctypes.c_uint64),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):  # type: ignore[attr-defined]
                return stat.ullTotalPhys / (1024**3)
        elif system == "Darwin":
            completed = subprocess.run(
                ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=10
            )
            if completed.returncode == 0:
                return int(completed.stdout.strip()) / (1024**3)
    except (OSError, ValueError, AttributeError):
        return None
    return None


def detect_memory() -> Prereq:
    total_gb = _total_memory_gb()
    if total_gb is None:
        return Prereq(
            name="memory",
            detected="unknown (could not query OS)",
            required=f">={MIN_MEMORY_GB:.0f} GB total",
            ok=True,
            remediation="Could not determine total memory automatically; verify manually if suites run out of RAM.",
            required_for=("client", "server", "gametest", "worldgen"),
        )
    ok = total_gb >= MIN_MEMORY_GB
    return Prereq(
        name="memory",
        detected=f"{total_gb:.1f} GB total",
        required=f">={MIN_MEMORY_GB:.0f} GB total (matches README system requirements)",
        ok=ok,
        remediation="8 GB minimum, 10 GB recommended. Close other applications or use a larger CI runner.",
        required_for=("client", "server", "gametest", "worldgen"),
    )


def detect_network(url: str = "https://api.modrinth.com/v2/tag/loader") -> Prereq:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            ok = 200 <= response.status < 300
            detected = f"HTTP {response.status} from {url}"
    except urllib.error.URLError as exc:
        ok = False
        detected = f"unreachable: {exc}"
    except socket.timeout:
        ok = False
        detected = "timed out"
    return Prereq(
        name="network",
        detected=detected,
        required="outbound HTTPS access to api.modrinth.com / cdn.modrinth.com",
        ok=ok,
        remediation="Required to resolve/download mods and query version hashes. Check firewall/proxy settings.",
        required_for=("artifact", "installer", "client", "server", "worldgen", "full"),
    )


def detect_all() -> list[Prereq]:
    return [
        detect_python(),
        detect_java(),
        detect_docker(),
        detect_powershell(),
        detect_bash(),
        detect_wsl(),
        detect_xvfb(),
        detect_disk_space(),
        detect_memory(),
        detect_network(),
    ]


def get(name: str) -> Prereq:
    for prereq in detect_all():
        if prereq.name == name:
            return prereq
    raise KeyError(name)


def format_table(prereqs: list[Prereq]) -> str:
    lines = [f"{'NAME':<14}{'STATUS':<9}{'DETECTED':<45}{'REQUIRED'}"]
    for prereq in prereqs:
        detected = (prereq.detected or "not found")[:43]
        lines.append(f"{prereq.name:<14}{prereq.status_word:<9}{detected:<45}{prereq.required}")
        if not prereq.ok:
            lines.append(f"{'':<14}fix: {prereq.remediation}")
            if prereq.required_for:
                lines.append(f"{'':<14}required for: {', '.join(prereq.required_for)}")
    return "\n".join(lines)
