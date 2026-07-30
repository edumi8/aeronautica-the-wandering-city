"""Structured test reporting shared by every suite.

Produces the two artifacts required by the pipeline spec:

- ``test-results/report.json``  (machine-readable, AI-friendly)
- ``test-results/junit.xml``    (consumed by CI test-report UIs)

Also emits GitHub Actions workflow annotations (``::error`` / ``::warning``)
when running under ``GITHUB_ACTIONS=true``, and prints a concise
human-readable summary to stdout that points at full logs instead of
flooding the console.
"""
from __future__ import annotations

import json
import os
import platform
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import quoteattr as xml_attr

#: The fixed failure-category taxonomy requested by the pipeline spec. Every
#: Result.category must be one of these strings (enforced by Result.__post_init__).
CATEGORIES = frozenset(
    {
        "prerequisite",
        "manifest",
        "artifact",
        "download",
        "checksum",
        "installer",
        "client-startup",
        "mod-loading",
        "world-loading",
        "server-startup",
        "server-health",
        "gametest",
        "worldgen",
        "performance",
        "timeout",
        # Not part of the requested taxonomy, but needed so a genuinely
        # uncategorizable internal error is still labelled honestly instead
        # of being forced into a misleading bucket.
        "internal",
    }
)

STATUSES = frozenset({"passed", "failed", "skipped"})


@dataclass
class Result:
    suite: str
    name: str
    status: str
    category: str
    duration_seconds: float = 0.0
    reason: str = ""
    command: str | None = None
    evidence: list[str] = field(default_factory=list)
    remediation: str | None = None

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"Invalid status {self.status!r} for result {self.name!r}")
        if self.category not in CATEGORIES:
            raise ValueError(f"Invalid category {self.category!r} for result {self.name!r}")

    def to_dict(self) -> dict:
        return {
            "suite": self.suite,
            "name": self.name,
            "status": self.status,
            "category": self.category,
            "duration_seconds": round(self.duration_seconds, 3),
            "reason": self.reason,
            "command": self.command,
            "evidence": list(self.evidence),
            "remediation": self.remediation,
        }


def _cdata_safe(text: str) -> str:
    """A CDATA section may contain anything except the literal "]]>"; split
    any occurrence so a log excerpt or path can never truncate/corrupt the
    surrounding XML.
    """
    return text.replace("]]>", "]]]]><![CDATA[>")


def _github_actions_active() -> bool:
    return os.environ.get("GITHUB_ACTIONS", "").lower() == "true"


def _emit_annotation(result: Result) -> None:
    if not _github_actions_active():
        return
    if result.status == "failed":
        level = "error"
    elif result.status == "skipped":
        level = "warning"
    else:
        return
    title = f"{result.suite}: {result.name}".replace("\n", " ")
    message = (result.reason or result.status).replace("\r", " ").replace("\n", " ")
    print(f"::{level} title={title}::{message}")


class Report:
    """Accumulates Results for one pipeline invocation and writes both
    machine-readable artifacts at the end.
    """

    def __init__(self, suite: str, output_dir: Path) -> None:
        self.suite = suite
        self.output_dir = output_dir
        self.results: list[Result] = []
        self.started_at = time.monotonic()
        self.started_wall = datetime.now(timezone.utc)

    def add(self, result: Result) -> Result:
        self.results.append(result)
        self._print_line(result)
        _emit_annotation(result)
        return result

    def record(
        self,
        *,
        suite: str | None = None,
        name: str,
        status: str,
        category: str,
        duration_seconds: float = 0.0,
        reason: str = "",
        command: str | None = None,
        evidence: list[str] | None = None,
        remediation: str | None = None,
    ) -> Result:
        return self.add(
            Result(
                suite=suite or self.suite,
                name=name,
                status=status,
                category=category,
                duration_seconds=duration_seconds,
                reason=reason,
                command=command,
                evidence=evidence or [],
                remediation=remediation,
            )
        )

    @staticmethod
    def _print_line(result: Result) -> None:
        marker = {"passed": "PASS", "failed": "FAIL", "skipped": "SKIP"}[result.status]
        line = f"[{marker}] {result.suite}: {result.name} ({result.duration_seconds:.2f}s)"
        print(line)
        if result.status != "passed" and result.reason:
            # Keep stdout concise: one reason line, evidence paths, not raw logs.
            print(f"       reason: {result.reason}")
        if result.status != "passed" and result.evidence:
            for path in result.evidence:
                print(f"       evidence: {path}")
        if result.status != "passed" and result.remediation:
            print(f"       fix: {result.remediation}")

    @property
    def counts(self) -> dict[str, int]:
        counts = {"passed": 0, "failed": 0, "skipped": 0}
        for result in self.results:
            counts[result.status] += 1
        return counts

    @property
    def duration_seconds(self) -> float:
        return time.monotonic() - self.started_at

    @property
    def success(self) -> bool:
        return self.counts["failed"] == 0

    def environment_block(self) -> dict:
        return {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "github_actions": _github_actions_active(),
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "github_sha": os.environ.get("GITHUB_SHA"),
        }

    def to_dict(self) -> dict:
        counts = self.counts
        return {
            "schema_version": 1,
            "suite": self.suite,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "environment": self.environment_block(),
            "summary": {
                "total": len(self.results),
                **counts,
                "duration_seconds": round(self.duration_seconds, 3),
            },
            "results": [r.to_dict() for r in self.results],
        }

    def write_json(self, path: Path | None = None) -> Path:
        path = path or (self.output_dir / "report.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return path

    def write_junit(self, path: Path | None = None) -> Path:
        path = path or (self.output_dir / "junit.xml")
        path.parent.mkdir(parents=True, exist_ok=True)
        counts = self.counts
        lines = ['<?xml version="1.0" encoding="UTF-8"?>']
        lines.append(
            '<testsuites name="aeronautica-test-pipeline" '
            f'tests="{len(self.results)}" failures="{counts["failed"]}" '
            f'skipped="{counts["skipped"]}" time="{self.duration_seconds:.3f}">'
        )
        # Group by suite so multiple suites merged into one report (e.g. `full`)
        # still produce readable <testsuite> blocks.
        by_suite: dict[str, list[Result]] = {}
        for result in self.results:
            by_suite.setdefault(result.suite, []).append(result)

        for suite_name, results in by_suite.items():
            suite_failed = sum(1 for r in results if r.status == "failed")
            suite_skipped = sum(1 for r in results if r.status == "skipped")
            suite_time = sum(r.duration_seconds for r in results)
            lines.append(
                f"  <testsuite name={xml_attr(suite_name)} tests=\"{len(results)}\" "
                f'failures="{suite_failed}" skipped="{suite_skipped}" time="{suite_time:.3f}">'
            )
            for result in results:
                classname = xml_attr(f"aeronautica.{suite_name}.{result.category}")
                testname = xml_attr(result.name)
                lines.append(
                    f"    <testcase classname={classname} name={testname} "
                    f'time="{result.duration_seconds:.3f}">'
                )
                if result.status == "failed":
                    message = xml_attr(result.reason or "failed")
                    lines.append(f"      <failure message={message}><![CDATA[")
                    lines.append(_cdata_safe(result.reason or "failed"))
                    if result.evidence:
                        lines.append(_cdata_safe("\nEvidence:\n" + "\n".join(result.evidence)))
                    if result.remediation:
                        lines.append(_cdata_safe(f"\nRemediation: {result.remediation}"))
                    lines.append("]]></failure>")
                elif result.status == "skipped":
                    message = xml_attr(result.reason or "skipped")
                    lines.append(f"      <skipped message={message}/>")
                lines.append("    </testcase>")
            lines.append("  </testsuite>")
        lines.append("</testsuites>")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def print_summary(self) -> None:
        counts = self.counts
        print("")
        print(f"===== {self.suite} summary =====")
        print(
            f"total={len(self.results)} passed={counts['passed']} "
            f"failed={counts['failed']} skipped={counts['skipped']} "
            f"duration={self.duration_seconds:.1f}s"
        )
        if counts["failed"]:
            print("")
            print("Failed:")
            for result in self.results:
                if result.status == "failed":
                    print(f"  - [{result.category}] {result.suite}: {result.name} -- {result.reason}")
        print(f"Full report: {self.output_dir / 'report.json'}")
        print(f"JUnit XML:   {self.output_dir / 'junit.xml'}")
