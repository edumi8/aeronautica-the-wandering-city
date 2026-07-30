"""Phase 7 driver: stages production mod jars and runs the Forge GameTest
project under tests/gametest/, then turns its output into report Results.

Ground truth used here (see docs.minecraftforge.net/en/1.20.x/misc/gametest):
`gradlew runGameTestServer` exits with a code equal to the number of failed
*required* tests -- 0 means every required test passed. That exit code is
the authoritative pass/fail signal; log-text scanning for the 10 known test
method names is a best-effort cross-check specifically to satisfy "fail if
zero tests are discovered" (a 0 exit code with no test names ever appearing
in the log means discovery silently found nothing, not that everything
passed).
"""
from __future__ import annotations

import platform
import re
from dataclasses import dataclass
from pathlib import Path

from . import paths
from .proc import run as run_command

GAMETEST_DIR = paths.GAMETEST_DIR
STAGE_JARS_SCRIPT = GAMETEST_DIR / "tools" / "stage_jars.py"

# Must match the @GameTest-annotated method names under
# tests/gametest/src/main/java/.../tests/*.java -- see TESTING.md "How to
# add a GameTest" for the rule that this list and the source must stay in
# sync (both are reviewed in the same PR).
KNOWN_TEST_METHODS = (
    "testCoreModsLoaded",
    "testRuntimeVersionsMatchCompatibilityMatrix",
    "testCriticalRegistryEntriesExist",
    "testCreateBlockPlacementAndTicking",
    "testCreateKineticRotationIsDeterministic",
    "testAdAstraDimensionsRegistered",
    "testBlockEntityNbtRoundTrip",
    "testEurekaShipBlocksPlaceAndReportShape",
    "testClockworkValkyrienSkiesIntegration",
    "testSupplementariesAmendmentsDecorationBlocks",
)
MINIMUM_EXPECTED_TESTS = len(KNOWN_TEST_METHODS)


@dataclass
class GameTestOutcome:
    ok: bool
    message: str
    discovered_tests: list[str]
    exit_code: int | None
    timed_out: bool
    log_path: Path | None


def stage_jars(*, timeout_seconds: float = 900, log_path: Path | None = None):
    import sys

    return run_command([sys.executable, str(STAGE_JARS_SCRIPT)], timeout_seconds=timeout_seconds, log_path=log_path)


def _gradlew() -> list[str]:
    if platform.system() == "Windows":
        return [str(GAMETEST_DIR / "gradlew.bat")]
    return [str(GAMETEST_DIR / "gradlew")]


def run_gametest_server(*, timeout_seconds: float = 2700, log_path: Path | None = None) -> GameTestOutcome:
    result = run_command(
        [*_gradlew(), "runGameTestServer", "--stacktrace", "--console=plain"],
        cwd=GAMETEST_DIR,
        timeout_seconds=timeout_seconds,
        log_path=log_path,
    )
    log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path and log_path.exists() else result.stdout_tail

    discovered = sorted({name for name in KNOWN_TEST_METHODS if re.search(re.escape(name), log_text)})

    if result.timed_out:
        return GameTestOutcome(False, f"gradlew runGameTestServer timed out after {timeout_seconds}s", discovered, None, True, log_path)

    if not discovered:
        return GameTestOutcome(
            False,
            "zero known GameTest methods were mentioned in the build output -- treating as a discovery "
            "failure regardless of exit code (a silent zero-test run must never read as success)",
            discovered,
            result.returncode,
            False,
            log_path,
        )

    if len(discovered) < MINIMUM_EXPECTED_TESTS:
        return GameTestOutcome(
            False,
            f"only {len(discovered)}/{MINIMUM_EXPECTED_TESTS} expected GameTest methods were discovered: {discovered}",
            discovered,
            result.returncode,
            False,
            log_path,
        )

    if result.returncode != 0:
        return GameTestOutcome(
            False,
            f"gradlew runGameTestServer exited {result.returncode} (equals the number of failed required tests)",
            discovered,
            result.returncode,
            False,
            log_path,
        )

    return GameTestOutcome(
        True,
        f"all {len(discovered)} discovered GameTest methods passed (exit code 0)",
        discovered,
        result.returncode,
        False,
        log_path,
    )
