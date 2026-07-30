"""Unit tests for prerequisite detection. Deliberately avoids asserting on
this machine's actual installed software (that would make the suite
environment-dependent); instead tests the Prereq dataclass contract and the
pure-logic pieces (Java version-string parsing, table formatting)."""
from __future__ import annotations

from aeronautica_testing import prereqs


def test_prereq_status_word_reflects_ok_and_mandatory():
    ok = prereqs.Prereq(name="x", detected="1.0", required=">=1.0", ok=True, remediation="")
    assert ok.status_word == "ok"

    missing_mandatory = prereqs.Prereq(name="x", detected=None, required=">=1.0", ok=False, remediation="install it", mandatory=True)
    assert missing_mandatory.status_word == "missing"

    missing_optional = prereqs.Prereq(name="x", detected=None, required=">=1.0", ok=False, remediation="install it", mandatory=False)
    assert missing_optional.status_word == "warning"


def test_detect_python_reports_running_interpreter():
    result = prereqs.detect_python()
    assert result.mandatory is True
    assert result.ok is True  # the pipeline itself requires 3.11+ to even import


def test_java_version_regex_parses_modern_scheme():
    match = prereqs._JAVA_VERSION_RE.search('openjdk version "17.0.16" 2025-07-15')
    assert match is not None
    assert match.group(1) == "17"


def test_java_version_regex_parses_legacy_1_8_scheme():
    match = prereqs._JAVA_VERSION_RE.search('java version "1.8.0_452"')
    assert match is not None
    first, second = match.group(1), match.group(2)
    major = int(second) if first == "1" and second else int(first)
    assert major == 8


def test_format_table_includes_remediation_for_failed_checks():
    checks = [
        prereqs.Prereq(name="docker", detected=None, required="present", ok=False, remediation="install docker", required_for=("server",)),
        prereqs.Prereq(name="python", detected="3.14.0", required=">=3.11", ok=True, remediation=""),
    ]
    table = prereqs.format_table(checks)
    assert "docker" in table
    assert "install docker" in table
    assert "required for: server" in table


def test_detect_all_returns_one_entry_per_known_check():
    names = {p.name for p in prereqs.detect_all()}
    assert names == {"python", "java", "docker", "powershell", "bash", "wsl", "xvfb", "disk-space", "memory", "network"}
