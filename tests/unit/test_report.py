"""Unit tests for the structured report/JUnit writers."""
from __future__ import annotations

import json

import pytest

from aeronautica_testing.report import Report, Result


def test_result_rejects_invalid_status():
    with pytest.raises(ValueError):
        Result(suite="fast", name="x", status="maybe", category="manifest")


def test_result_rejects_invalid_category():
    with pytest.raises(ValueError):
        Result(suite="fast", name="x", status="passed", category="not-a-real-category")


def test_report_counts_and_success(tmp_path):
    report = Report(suite="fast", output_dir=tmp_path)
    report.record(name="a", status="passed", category="manifest")
    report.record(name="b", status="failed", category="artifact", reason="boom")
    report.record(name="c", status="skipped", category="prerequisite")

    assert report.counts == {"passed": 1, "failed": 1, "skipped": 1}
    assert report.success is False


def test_report_all_passed_is_success(tmp_path):
    report = Report(suite="fast", output_dir=tmp_path)
    report.record(name="a", status="passed", category="manifest")
    assert report.success is True


def test_write_json_round_trips(tmp_path):
    report = Report(suite="artifact", output_dir=tmp_path)
    report.record(
        name="artifact:structure",
        status="failed",
        category="artifact",
        reason="bad path",
        command="python scripts/validate.py --build",
        evidence=["test-results/evidence/x.log"],
        remediation="fix the path",
    )
    path = report.write_json()
    data = json.loads(path.read_text(encoding="utf-8"))

    assert data["schema_version"] == 1
    assert data["suite"] == "artifact"
    assert data["summary"]["total"] == 1
    assert data["summary"]["failed"] == 1
    result = data["results"][0]
    assert result["name"] == "artifact:structure"
    assert result["status"] == "failed"
    assert result["category"] == "artifact"
    assert result["remediation"] == "fix the path"


def test_write_junit_produces_well_formed_xml(tmp_path):
    import xml.etree.ElementTree as ET

    report = Report(suite="fast", output_dir=tmp_path)
    report.record(name="a", status="passed", category="manifest")
    report.record(name="b", status="failed", category="artifact", reason="boom")
    report.record(name="c", status="skipped", category="prerequisite", reason="no docker")

    path = report.write_junit()
    root = ET.fromstring(path.read_text(encoding="utf-8"))  # raises on malformed XML

    assert root.tag == "testsuites"
    assert root.attrib["tests"] == "3"
    assert root.attrib["failures"] == "1"
    assert root.attrib["skipped"] == "1"

    testcases = root.findall(".//testcase")
    assert len(testcases) == 3
    failed_case = next(tc for tc in testcases if tc.attrib["name"] == "b")
    assert failed_case.find("failure") is not None
    skipped_case = next(tc for tc in testcases if tc.attrib["name"] == "c")
    assert skipped_case.find("skipped") is not None


def test_junit_escapes_special_characters(tmp_path):
    import xml.etree.ElementTree as ET

    report = Report(suite="fast", output_dir=tmp_path)
    report.record(name='weird<>&"name', status="failed", category="manifest", reason="reason with <tags> & \"quotes\"")
    path = report.write_junit()
    ET.fromstring(path.read_text(encoding="utf-8"))  # must not raise


def test_junit_reason_containing_cdata_terminator_does_not_corrupt_xml(tmp_path):
    import xml.etree.ElementTree as ET

    report = Report(suite="fast", output_dir=tmp_path)
    report.record(name="a", status="failed", category="manifest", reason="log excerpt contains ]]> right here")
    path = report.write_junit()
    root = ET.fromstring(path.read_text(encoding="utf-8"))  # must not raise
    failure_text = root.find(".//failure").text
    assert "]]>" in failure_text


def test_environment_block_reports_github_actions_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    report = Report(suite="fast", output_dir=tmp_path)
    env = report.environment_block()
    assert env["github_actions"] is True
    assert env["github_sha"] == "abc123"
