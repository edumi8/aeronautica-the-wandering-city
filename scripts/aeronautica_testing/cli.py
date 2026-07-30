"""argparse entry point shared by scripts/test_pipeline.py and both platform
wrappers (scripts/test.sh, scripts/test.ps1). See TESTING.md for the full
suite catalogue.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import paths, suites
from .context import RunContext
from .exit_codes import ExitCode, worst
from .report import Report
from .workdir import WorkdirManager


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="test_pipeline.py",
        description="Aeronautica: The Wandering City -- local/CI test pipeline. See TESTING.md.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("suite", choices=suites.SUITE_NAMES, help="Which suite to run.")
    parser.add_argument(
        "--allow-missing-runtime",
        action="store_true",
        help="Missing prerequisites (Docker/Java/Xvfb/...) cause the affected suite to be SKIPPED "
        "instead of FAILED. Without this flag, `full` and individual suites fail loudly on a missing "
        "required prerequisite -- they never silently skip.",
    )
    parser.add_argument(
        "--keep-workdir",
        action="store_true",
        help="Do not delete temporary instance/build directories on exit (useful for debugging a failure).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=paths.DEFAULT_OUTPUT_DIR,
        help="Where to write report.json, junit.xml, and per-suite evidence subdirectories.",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=paths.DEFAULT_CACHE_DIR,
        help="Content-addressed download cache shared across suites (override AERONAUTICA_TEST_CACHE "
        "env var in CI to key it by manifest hash / OS / MC / Forge / Java version).",
    )
    parser.add_argument(
        "--json-report",
        action="store_true",
        help="Also print the full JSON report to stdout at the end (in addition to writing the file).",
    )
    parser.add_argument(
        "--timeout-multiplier",
        type=float,
        default=1.0,
        help="Scale every suite's default timeouts (e.g. 2.0 doubles them) for slower machines/CI runners.",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="`artifact` suite only: skip building and reuse whatever is already in releases/ "
        "(downloaded from the build job's uploaded artifact). Skips the download/hash/reproducible-build "
        "checks too (already proven once by the build job) and only runs structural + independent-install "
        "checks. Used by the per-OS installer-verification CI jobs; local runs normally omit this.",
    )
    parser.add_argument(
        "--worldgen-radius",
        type=int,
        default=50,
        help="Chunk radius for the `worldgen` suite (spec: small for CI, larger for nightly -- pass a bigger value from the nightly workflow).",
    )
    return parser


_DEFAULT_TIMEOUTS = {
    "pytest": 300,
    "build": 1200,
    "download": 120,
    "installer": 900,
    "client_install_forge": 900,
    "client_stage_mods": 900,
    "client_launch": 600,
    "server_health": 900,
    "server_stop": 120,
    "gametest_stage": 900,
    "gametest_run": 3600,
    "worldgen_run": 1800,
}


def _make_context(args: argparse.Namespace) -> RunContext:
    timeouts = {k: v * args.timeout_multiplier for k, v in _DEFAULT_TIMEOUTS.items()}
    workdir_base = args.output_dir / "work"
    return RunContext(
        output_dir=args.output_dir,
        cache_dir=args.cache_dir,
        allow_missing_runtime=args.allow_missing_runtime,
        keep_workdir=args.keep_workdir,
        skip_build=args.skip_build,
        workdir=WorkdirManager(keep=args.keep_workdir, base_dir=workdir_base),
        timeouts=timeouts,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse already printed usage/help; normalize to our exit codes
        # instead of trusting argparse's own 0/2 (never let a parse issue
        # look like suite success).
        code = exc.code if isinstance(exc.code, int) else ExitCode.USAGE_ERROR
        return ExitCode.OK if code == 0 else ExitCode.USAGE_ERROR

    ctx = _make_context(args)
    report = Report(suite=args.suite, output_dir=args.output_dir)

    try:
        if args.suite == "full":
            suites.run_full(report, ctx, worldgen_radius=args.worldgen_radius)
        elif args.suite == "worldgen":
            suites.run_worldgen(report, ctx, radius=args.worldgen_radius)
        else:
            suites.ALL_SUITES[args.suite](report, ctx)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        _finish(report, args, ctx)
        return ExitCode.INTERRUPTED
    except Exception as exc:  # noqa: BLE001 - must never look like success
        report.record(
            name=f"{args.suite}:internal-error",
            status="failed",
            category="internal",
            reason=f"unhandled exception in the pipeline itself: {exc!r}",
            remediation="This is a pipeline bug, not a modpack problem. Please file an issue with the full traceback below.",
        )
        import traceback

        traceback.print_exc()
        _finish(report, args, ctx)
        return ExitCode.INTERNAL_ERROR
    finally:
        retained = ctx.workdir.cleanup()
        if retained:
            print(f"\nRetained work directories ({'--keep-workdir' if ctx.keep_workdir else 'cleanup failed'}):")
            for path in retained:
                print(f"  {path}")

    _finish(report, args, ctx)

    if report.counts["failed"] > 0:
        return ExitCode.TESTS_FAILED
    if any(r.category == "prerequisite" and r.status == "failed" for r in report.results):
        return ExitCode.PREREQUISITE_MISSING
    return ExitCode.OK


def _finish(report: Report, args: argparse.Namespace, _ctx: RunContext) -> None:
    report.write_json()
    report.write_junit()
    report.print_summary()
    if args.json_report:
        import json

        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())
