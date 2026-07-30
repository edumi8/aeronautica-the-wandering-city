"""Central, single-source-of-truth filesystem locations for the repository.

Every module in the pipeline (and ``scripts/validate.py``) should import
paths from here instead of recomputing ``Path(__file__).resolve().parents[N]``
so that moving a file never silently breaks a sibling module.
"""
from __future__ import annotations

from pathlib import Path

# scripts/aeronautica_testing/paths.py -> repository root is two parents up.
ROOT = Path(__file__).resolve().parents[2]

SCRIPTS_DIR = ROOT / "scripts"
VALIDATE_PY = SCRIPTS_DIR / "validate.py"
MODPACK_DIR = ROOT / "modpack"
MANIFEST_PATH = MODPACK_DIR / "manifest.json"
INDEX_PATH = MODPACK_DIR / "modrinth.index.json"
ICON_PATH = MODPACK_DIR / "icon.png"

OVERRIDES_PATH = ROOT / "overrides"
CLIENT_OVERRIDES_PATH = ROOT / "client-overrides"
SERVER_OVERRIDES_PATH = ROOT / "server-overrides"

RELEASES_PATH = ROOT / "releases"

TESTS_DIR = ROOT / "tests"
UNIT_TESTS_DIR = TESTS_DIR / "unit"
GAMETEST_DIR = TESTS_DIR / "gametest"
WORLDGEN_DIR = TESTS_DIR / "worldgen"
FIXTURES_DIR = UNIT_TESTS_DIR / "fixtures"

DOCKER_DIR = ROOT / "docker"

DEFAULT_OUTPUT_DIR = ROOT / "test-results"
DEFAULT_REPORT_JSON = "report.json"
DEFAULT_REPORT_JUNIT = "junit.xml"

# Content-addressed download cache shared by artifact/installer/client/server
# suites so a single local run does not re-download ~150 MB of mods per
# suite. Override with the AERONAUTICA_TEST_CACHE environment variable (used
# by CI to key caches by manifest hash / OS / MC / Forge / Java version).
DEFAULT_CACHE_DIR = ROOT / ".cache" / "aeronautica-test-downloads"

MC_VERSION = "1.20.1"
LOADER = "forge"
FORGE_VERSION = "47.4.10"
REQUIRED_JAVA_MAJOR = 17
