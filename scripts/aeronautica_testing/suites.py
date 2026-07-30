"""Suite definitions: the 8 commands scripts/test_pipeline.py exposes.

Every suite has the identical shape ``run(report, ctx) -> None`` and reports
through ``report.record(...)`` as it goes, so `full` is simply "call every
suite in order" with no separate CI-only code path.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Callable

from . import (
    client_smoke,
    compat,
    gametest_runner,
    installer_check,
    modrinth_hashes,
    mrpack_validate,
    prereqs,
    reproducible,
    server_smoke,
    worldgen_perf,
)
from . import paths
from .context import RunContext
from .proc import run as run_command
from .report import Report

SUITE_NAMES = ("prereqs", "fast", "artifact", "client", "server", "gametest", "worldgen", "full")


# --------------------------------------------------------------------------
# prereqs
# --------------------------------------------------------------------------


def run_prereqs(report: Report, _ctx: RunContext) -> None:
    for check in prereqs.detect_all():
        if check.ok:
            status = "passed"
        elif check.mandatory:
            status = "failed"
        else:
            status = "skipped"
        report.record(
            name=f"prereq:{check.name}",
            status=status,
            category="prerequisite",
            reason="" if check.ok else f"detected={check.detected!r} required={check.required!r}",
            remediation=None if check.ok else check.remediation,
            evidence=[] if check.ok else [f"required_for={','.join(check.required_for)}"],
        )
    print("\n" + prereqs.format_table(prereqs.detect_all()))


def _preflight(report: Report, ctx: RunContext, suite: str, required_checks: list[str]) -> bool:
    """Runs the named prereq checks; records a single prerequisite Result.
    Returns True if the suite may proceed.
    """
    all_checks = {p.name: p for p in prereqs.detect_all()}
    missing = [name for name in required_checks if not all_checks[name].ok]
    if not missing:
        return True

    reasons = "; ".join(f"{name}: {all_checks[name].detected!r}" for name in missing)
    if ctx.allow_missing_runtime:
        report.record(
            suite=suite,
            name=f"{suite}:preflight",
            status="skipped",
            category="prerequisite",
            reason=f"missing prerequisites ({reasons}) -- suite skipped because --allow-missing-runtime was passed",
            remediation="; ".join(all_checks[name].remediation for name in missing),
        )
        return False

    report.record(
        suite=suite,
        name=f"{suite}:preflight",
        status="failed",
        category="prerequisite",
        reason=f"missing required prerequisites: {reasons}",
        remediation="; ".join(all_checks[name].remediation for name in missing) + " -- or pass --allow-missing-runtime to skip this suite instead of failing.",
    )
    return False


# --------------------------------------------------------------------------
# fast: static, network-free checks
# --------------------------------------------------------------------------


def run_fast(report: Report, ctx: RunContext) -> None:
    _fast_compileall(report, ctx)
    _fast_manifest_structure(report, ctx)
    _fast_compat_matrix(report, ctx)
    _fast_pytest(report, ctx)
    _fast_existing_artifact(report, ctx)


def _fast_compileall(report: Report, ctx: RunContext) -> None:
    started = time.monotonic()
    log_path = ctx.evidence_dir("fast") / "compileall.log"
    result = run_command(
        [sys.executable, "-m", "compileall", "-q", str(paths.SCRIPTS_DIR / "aeronautica_testing")],
        cwd=paths.ROOT,
        timeout_seconds=60,
        log_path=log_path,
    )
    report.record(
        name="fast:compileall",
        status="passed" if result.returncode == 0 else "failed",
        category="manifest",
        duration_seconds=time.monotonic() - started,
        reason="" if result.returncode == 0 else result.stdout_tail,
        command="python -m compileall scripts/aeronautica_testing",
        evidence=[str(log_path)],
        remediation=None if result.returncode == 0 else "Fix the reported Python syntax error.",
    )


def _fast_manifest_structure(report: Report, ctx: RunContext) -> None:
    started = time.monotonic()
    try:
        manifest = json.loads(paths.MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report.record(
            name="fast:manifest-structure",
            status="failed",
            category="manifest",
            duration_seconds=time.monotonic() - started,
            reason=f"could not load {paths.MANIFEST_PATH}: {exc}",
            remediation="Run `python scripts/validate.py` once to regenerate the manifest, or fix the JSON error.",
        )
        return

    problems = []
    if manifest.get("loader") != "forge":
        problems.append("loader must be 'forge'")
    if manifest.get("minecraft") != paths.MC_VERSION:
        problems.append(f"minecraft must be {paths.MC_VERSION!r}")
    if manifest.get("forge_version") != paths.FORGE_VERSION:
        problems.append(f"forge_version must be {paths.FORGE_VERSION!r}")
    if not paths.ICON_PATH.exists():
        problems.append(f"missing {paths.ICON_PATH}")
    if not paths.OVERRIDES_PATH.exists():
        problems.append(f"missing {paths.OVERRIDES_PATH}")
    if not manifest.get("resolved_mods"):
        problems.append("manifest has no resolved_mods -- run `python scripts/validate.py` first")

    report.record(
        name="fast:manifest-structure",
        status="passed" if not problems else "failed",
        category="manifest",
        duration_seconds=time.monotonic() - started,
        reason="; ".join(problems),
        remediation=None if not problems else "Fix modpack/manifest.json, or re-run scripts/validate.py.",
    )


def _fast_compat_matrix(report: Report, ctx: RunContext) -> None:
    started = time.monotonic()
    try:
        manifest = json.loads(paths.MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report.record(
            name="fast:compatibility-matrix",
            status="skipped",
            category="manifest",
            reason=f"manifest unreadable: {exc}",
        )
        return

    versions = {m["slug"]: m.get("version_number", "") for m in manifest.get("resolved_mods", [])}
    pins = {m["slug"]: m.get("version") for m in manifest.get("mods", []) if m.get("version")}
    issues = compat.evaluate(versions, pins)
    report.record(
        name="fast:compatibility-matrix",
        status="passed" if not issues else "failed",
        category="manifest",
        duration_seconds=time.monotonic() - started,
        reason="; ".join(f"[{i.rule}] {i.message}" for i in issues),
        remediation=None if not issues else "See scripts/aeronautica_testing/compat.py for the violated rule.",
    )


def _fast_pytest(report: Report, ctx: RunContext) -> None:
    started = time.monotonic()
    log_path = ctx.evidence_dir("fast") / "pytest.log"
    result = run_command(
        [sys.executable, "-m", "pytest", str(paths.UNIT_TESTS_DIR), "-q"],
        cwd=paths.ROOT,
        timeout_seconds=ctx.timeout("pytest", 300),
        log_path=log_path,
    )
    report.record(
        name="fast:pytest",
        status="passed" if result.returncode == 0 else "failed",
        category="manifest",
        duration_seconds=time.monotonic() - started,
        reason="" if result.returncode == 0 else result.stdout_tail,
        command="python -m pytest tests/unit -q",
        evidence=[str(log_path)],
        remediation=None if result.returncode == 0 else "Inspect the pytest log; fix the failing assertion.",
    )


def _fast_existing_artifact(report: Report, ctx: RunContext) -> None:
    candidates = sorted(paths.RELEASES_PATH.glob("*.mrpack")) if paths.RELEASES_PATH.exists() else []
    if not candidates:
        report.record(
            name="fast:existing-artifact-structure",
            status="skipped",
            category="artifact",
            reason="no releases/*.mrpack present yet -- run the `artifact` suite to build one",
        )
        return
    manifest = json.loads(paths.MANIFEST_PATH.read_text(encoding="utf-8")) if paths.MANIFEST_PATH.exists() else None
    started = time.monotonic()
    issues = mrpack_validate.validate_archive(
        candidates[-1], manifest=manifest, expected_mc=paths.MC_VERSION, expected_forge=paths.FORGE_VERSION
    )
    report.record(
        name=f"fast:existing-artifact-structure ({candidates[-1].name})",
        status="passed" if not issues else "failed",
        category="artifact",
        duration_seconds=time.monotonic() - started,
        reason="; ".join(str(i) for i in issues[:10]) + (f" (+{len(issues) - 10} more)" if len(issues) > 10 else ""),
        remediation=None if not issues else "Run the `artifact` suite for the full breakdown.",
    )


# --------------------------------------------------------------------------
# artifact: build + deep structural/security/hash validation + reproducibility
# --------------------------------------------------------------------------


def run_artifact(report: Report, ctx: RunContext) -> None:
    """Full mode (default): build fresh into releases/, then run every
    static/download/hash/reproducibility check. Used by local dev and the
    CI build-and-validate job.

    ``ctx.skip_build`` mode: assume releases/ already holds the artifact
    the build job produced (downloaded via actions/download-artifact) and
    only run the OS-specific parts that are worth repeating per runner --
    structural checks and the independent installer check. Download/hash/
    reproducible-build were already proven once by the build job; redoing
    them on every OS would just re-download ~150 MB of mods for no new
    signal. See TESTING.md "GitHub workflow structure".
    """
    if not ctx.skip_build:
        if not _preflight(report, ctx, "artifact", ["network"]):
            return
        started = time.monotonic()
        build_log = ctx.evidence_dir("artifact") / "build.log"
        result = run_command(
            [sys.executable, str(paths.VALIDATE_PY), "--build", "--verify-downloads"],
            cwd=paths.ROOT,
            timeout_seconds=ctx.timeout("build", 1200),
            log_path=build_log,
        )
        report.record(
            name="artifact:build",
            status="passed" if result.returncode == 0 else "failed",
            category="artifact",
            duration_seconds=time.monotonic() - started,
            reason="" if result.returncode == 0 else result.stdout_tail,
            command="python scripts/validate.py --build --verify-downloads",
            evidence=[str(build_log)],
            remediation=None if result.returncode == 0 else "Inspect the build log for the failing mod/download.",
        )
        if result.returncode != 0:
            return
    else:
        mrpacks = sorted(paths.RELEASES_PATH.glob("*.mrpack")) if paths.RELEASES_PATH.exists() else []
        if not mrpacks:
            report.record(
                name="artifact:build",
                status="failed",
                category="artifact",
                reason=f"--skip-build was set but no *.mrpack exists under {paths.RELEASES_PATH} "
                "-- download the build job's artifact into releases/ first",
                remediation="actions/download-artifact the build-and-validate job's `releases` artifact before this job.",
            )
            return
        report.record(name="artifact:build", status="skipped", category="artifact", reason="--skip-build: reusing the artifact produced by the build job")

    if not paths.MANIFEST_PATH.exists():
        report.record(name="artifact:manifest-present", status="failed", category="manifest", reason=f"{paths.MANIFEST_PATH} missing")
        return
    manifest = json.loads(paths.MANIFEST_PATH.read_text(encoding="utf-8"))
    release_name = f"{manifest['name'].replace(':', '').replace(' ', '-')}-{manifest['version']}"
    mrpack_path = paths.RELEASES_PATH / f"{release_name}.mrpack"
    manual_zip_path = paths.RELEASES_PATH / f"{release_name}-manual.zip"

    _artifact_structural_checks(report, mrpack_path, manual_zip_path, manifest)
    _artifact_sha256_sidecars(report)
    run_installer_check(report, ctx, suite="artifact")

    if not ctx.skip_build:
        _artifact_download_verification(report, ctx, mrpack_path)
        _artifact_modrinth_hash_check(report, mrpack_path)
        _artifact_reproducible_build(report, ctx)


def _artifact_structural_checks(report: Report, mrpack_path: Path, manual_zip_path: Path, manifest: dict) -> None:
    for label, path in (("mrpack", mrpack_path), ("manual-zip", manual_zip_path)):
        started = time.monotonic()
        issues = mrpack_validate.validate_archive(
            path,
            manifest=manifest if label == "mrpack" else None,
            expected_mc=paths.MC_VERSION,
            expected_forge=paths.FORGE_VERSION,
        )
        report.record(
            name=f"artifact:structure ({label})",
            status="passed" if not issues else "failed",
            category="artifact",
            duration_seconds=time.monotonic() - started,
            reason="; ".join(str(i) for i in issues[:15]) + (f" (+{len(issues) - 15} more)" if len(issues) > 15 else ""),
            remediation=None if not issues else "See scripts/aeronautica_testing/mrpack_validate.py for the violated check.",
        )


def _artifact_download_verification(report: Report, ctx: RunContext, mrpack_path: Path) -> None:
    started = time.monotonic()
    artifact, _ = mrpack_validate.load_archive(mrpack_path)
    if artifact is None or artifact.index is None:
        report.record(name="artifact:download-verification", status="failed", category="download", reason="could not reload archive index")
        return
    results = mrpack_validate.verify_all_downloads(artifact.index, cache_dir=ctx.cache_dir, timeout=ctx.timeout("download", 120))
    failures = [r for r in results if not r.ok]
    report.record(
        name=f"artifact:download-verification ({len(results)} files)",
        status="passed" if not failures else "failed",
        category="download",
        duration_seconds=time.monotonic() - started,
        reason="; ".join(f"{f.path}: {f.message}" for f in failures[:10]),
        remediation=None if not failures else "A declared download URL's actual bytes do not match its declared hash/size.",
    )


def _artifact_modrinth_hash_check(report: Report, mrpack_path: Path) -> None:
    started = time.monotonic()
    artifact, _ = mrpack_validate.load_archive(mrpack_path)
    if artifact is None or artifact.index is None:
        report.record(name="artifact:modrinth-hash-lookup", status="failed", category="checksum", reason="could not reload archive index")
        return
    issues = modrinth_hashes.verify_index_against_modrinth(artifact.index, expected_mc=paths.MC_VERSION)
    report.record(
        name="artifact:modrinth-hash-lookup",
        status="passed" if not issues else "failed",
        category="checksum",
        duration_seconds=time.monotonic() - started,
        reason="; ".join(str(i) for i in issues[:10]),
        command="POST https://api.modrinth.com/v2/version_files",
        remediation=None if not issues else "A Modrinth-hosted file's hash does not resolve, or resolves to a version that does not support 1.20.1/forge.",
    )


def _artifact_sha256_sidecars(report: Report) -> None:
    started = time.monotonic()
    issues = mrpack_validate.verify_sha256_sidecars(paths.RELEASES_PATH)
    report.record(
        name="artifact:sha256-sidecars",
        status="passed" if not issues else "failed",
        category="checksum",
        duration_seconds=time.monotonic() - started,
        reason="; ".join(str(i) for i in issues),
        remediation=None if not issues else "Regenerate releases/SHA256SUMS via the build.",
    )


def _artifact_reproducible_build(report: Report, ctx: RunContext) -> None:
    started = time.monotonic()
    dir_a = ctx.workdir.new("repro-a")
    dir_b = ctx.workdir.new("repro-b")
    outcome, _results = reproducible.run_reproducible_build_check(
        build_a_dir=dir_a,
        build_b_dir=dir_b,
        verify_downloads=False,
        timeout_seconds=ctx.timeout("build", 1200),
        log_dir=ctx.evidence_dir("artifact"),
    )
    report.record(
        name="artifact:reproducible-build",
        status="passed" if outcome.ok else "failed",
        category="artifact",
        duration_seconds=time.monotonic() - started,
        reason=outcome.message,
        remediation=None if outcome.ok else "The build is not deterministic -- check for timestamp/ordering/permission drift in scripts/validate.py's archive writer.",
    )


# --------------------------------------------------------------------------
# installer (used standalone by CLI and reused by client suite)
# --------------------------------------------------------------------------


def run_installer_check(report: Report, ctx: RunContext, suite: str = "installer") -> installer_check.InstallCheckOutcome | None:
    manifest = json.loads(paths.MANIFEST_PATH.read_text(encoding="utf-8")) if paths.MANIFEST_PATH.exists() else None
    mrpacks = sorted(paths.RELEASES_PATH.glob("*.mrpack")) if paths.RELEASES_PATH.exists() else []
    if not mrpacks or manifest is None:
        report.record(
            suite=suite,
            name="installer:independent-install",
            status="skipped",
            category="installer",
            reason="no built .mrpack found -- run the `artifact` suite first",
        )
        return None

    mrpack_path = mrpacks[-1]
    instance_dir = ctx.workdir.new("independent-install")
    inventory_path = ctx.evidence_dir(suite) / "installed-inventory.json"
    log_path = ctx.evidence_dir(suite) / "installer.log"

    started = time.monotonic()
    outcome = installer_check.run_installer(
        mrpack_path=mrpack_path,
        instance_dir=instance_dir,
        inventory_path=inventory_path,
        timeout_seconds=ctx.timeout("installer", 900),
        log_path=log_path,
        skip_dependencies=True,
    )
    if outcome.issues:
        report.record(
            suite=suite,
            name="installer:independent-install",
            status="failed",
            category="installer",
            duration_seconds=time.monotonic() - started,
            reason="; ".join(str(i) for i in outcome.issues[:10]),
            evidence=[str(log_path)],
            remediation="Inspect the installer worker log; minecraft-launcher-lib may have changed its mrpack API.",
        )
        return outcome

    reloaded_artifact, reload_issues = mrpack_validate.load_archive(mrpack_path)
    if reloaded_artifact is None or reloaded_artifact.index is None:
        report.record(
            suite=suite,
            name="installer:independent-install",
            status="failed",
            category="installer",
            reason=f"could not reload {mrpack_path} to compare against the installed inventory: {reload_issues}",
        )
        return outcome
    compare_issues = installer_check.compare_inventory(outcome.inventory, mrpack_path=mrpack_path, index=reloaded_artifact.index)
    report.record(
        suite=suite,
        name=f"installer:independent-install ({outcome.inventory.get('file_count')} files)",
        status="passed" if not compare_issues else "failed",
        category="installer",
        duration_seconds=time.monotonic() - started,
        reason="; ".join(str(i) for i in compare_issues[:10]),
        evidence=[str(inventory_path), str(log_path)],
        remediation=None if not compare_issues else "See installer_check.compare_inventory for the specific mismatch.",
    )
    return outcome


# --------------------------------------------------------------------------
# client
# --------------------------------------------------------------------------


def run_client(report: Report, ctx: RunContext) -> None:
    if not _preflight(report, ctx, "client", ["java", "network"]):
        return

    mrpacks = sorted(paths.RELEASES_PATH.glob("*.mrpack")) if paths.RELEASES_PATH.exists() else []
    if not mrpacks:
        report.record(suite="client", name="client:mrpack-available", status="failed", category="prerequisite", reason="no built .mrpack -- run the `artifact` suite first")
        return

    mrpack_path = mrpacks[-1]
    gamedir = ctx.workdir.new("client-gamedir")
    evidence = ctx.evidence_dir("client")

    steps: list[tuple[str, Callable[[], client_smoke.StepOutcome]]] = [
        ("client:install-forge", lambda: client_smoke.install_forge_client(gamedir, ctx.cache_dir, log_path=evidence / "forge-install.log")),
        ("client:verify-forge-version", lambda: client_smoke.verify_installed_forge_version(gamedir)),
        ("client:stage-pack-mods", lambda: client_smoke.stage_pack_mods(mrpack_path, gamedir, log_path=evidence / "stage-mods.log")),
        ("client:stage-test-helper-mod", lambda: client_smoke.stage_test_helper_mod(gamedir, ctx.cache_dir)),
        ("client:download-headlessmc", lambda: client_smoke.download_headlessmc(ctx.cache_dir)),
    ]

    for name, step in steps:
        started = time.monotonic()
        outcome = step()
        report.record(
            suite="client",
            name=name,
            status="passed" if outcome.ok else "failed",
            category="client-startup",
            duration_seconds=time.monotonic() - started,
            reason="" if outcome.ok else outcome.message,
            evidence=outcome.evidence,
        )
        if not outcome.ok:
            _client_collect_failure_evidence(report, gamedir, evidence)
            return

    headlessmc_jar = ctx.cache_dir / f"headlessmc-launcher-{client_smoke.HEADLESSMC_VERSION}.jar"
    started = time.monotonic()
    launch_outcome = client_smoke.run_headless_session(
        headlessmc_jar, gamedir, timeout_seconds=ctx.timeout("client_launch", 600), log_path=evidence / "session-1.log"
    )
    report.record(
        suite="client",
        name="client:launch-and-load-world",
        status="passed" if launch_outcome.ok else "failed",
        category="world-loading",
        duration_seconds=time.monotonic() - started,
        reason="" if launch_outcome.ok else launch_outcome.message,
        evidence=launch_outcome.evidence,
        remediation=None if launch_outcome.ok else "Inspect session-1.log; ensure Xvfb/software GL are available (see prereqs).",
    )
    if not launch_outcome.ok:
        _client_collect_failure_evidence(report, gamedir, evidence)
        return

    saves_before = client_smoke._saves_snapshot(gamedir)
    started = time.monotonic()
    second_outcome = client_smoke.run_headless_session(
        headlessmc_jar, gamedir, timeout_seconds=ctx.timeout("client_launch", 600), log_path=evidence / "session-2.log"
    )
    saves_after = client_smoke._saves_snapshot(gamedir)
    reopened = bool(saves_before) and set(saves_before) <= set(saves_after) and any(
        saves_after.get(name, 0) > saves_before.get(name, 0) for name in saves_before
    )
    report.record(
        suite="client",
        name="client:reopen-same-world",
        status="passed" if second_outcome.ok and reopened else ("skipped" if second_outcome.ok else "failed"),
        category="world-loading",
        duration_seconds=time.monotonic() - started,
        reason=("world was not confirmed reopened (mc-runtime-test may create a fresh world per run)" if second_outcome.ok and not reopened else second_outcome.message),
        evidence=second_outcome.evidence,
    )


def _client_collect_failure_evidence(report: Report, gamedir: Path, evidence: Path) -> None:
    written = client_smoke.collect_failure_evidence(gamedir, evidence)
    report.record(
        suite="client",
        name="client:failure-evidence",
        status="skipped",
        category="client-startup",
        reason="collected latest.log/debug.log/crash-reports/screenshot for debugging",
        evidence=written,
    )


# --------------------------------------------------------------------------
# server
# --------------------------------------------------------------------------


def run_server(report: Report, ctx: RunContext) -> None:
    if not _preflight(report, ctx, "server", ["docker"]):
        return

    mrpacks = sorted(paths.RELEASES_PATH.glob("*.mrpack")) if paths.RELEASES_PATH.exists() else []
    if not mrpacks:
        report.record(suite="server", name="server:mrpack-available", status="failed", category="prerequisite", reason="no built .mrpack -- run the `artifact` suite first")
        return
    mrpack_path = mrpacks[-1]

    name = server_smoke.container_name()
    data_dir = ctx.workdir.new("server-data")
    evidence = ctx.evidence_dir("server")

    started = time.monotonic()
    start_result = server_smoke.start_container(name=name, mrpack_path=mrpack_path, data_dir=data_dir, log_path=evidence / "docker-run.log")
    if start_result.returncode != 0:
        report.record(suite="server", name="server:start-container", status="failed", category="server-startup", reason=start_result.stdout_tail, evidence=[str(evidence / "docker-run.log")])
        return
    report.record(suite="server", name="server:start-container", status="passed", category="server-startup", duration_seconds=time.monotonic() - started, evidence=[name])

    try:
        _server_run_checks(report, name, evidence, ctx)
    finally:
        server_smoke.collect_evidence(name, evidence)
        server_smoke.copy_data_logs(data_dir, evidence)
        server_smoke.remove_container(name)


def _server_run_checks(report: Report, name: str, evidence: Path, ctx: RunContext) -> None:
    first_boot_since = server_smoke.container_started_at(name)
    started = time.monotonic()
    health = server_smoke.wait_for_healthy_or_done(
        name, timeout_seconds=ctx.timeout("server_health", 900), log_path=evidence / "startup.log", since=first_boot_since
    )
    report.record(suite="server", name="server:reach-healthy", status="passed" if health.ok else "failed", category="server-health", duration_seconds=time.monotonic() - started, reason=health.message, evidence=health.evidence)
    if not health.ok:
        return

    java_check = server_smoke.verify_java_version(name)
    report.record(suite="server", name="server:java-version", status="passed" if java_check.ok else "failed", category="server-startup", reason=java_check.message)

    forge_check = server_smoke.verify_forge_layout(name, expected_mc=paths.MC_VERSION, expected_forge=paths.FORGE_VERSION)
    report.record(suite="server", name="server:forge-version", status="passed" if forge_check.ok else "failed", category="server-startup", reason=forge_check.message)

    list_result = server_smoke.rcon_verified(name, "list", "players online")
    report.record(suite="server", name="server:rcon-list", status="passed" if list_result.ok else "failed", category="server-health", reason=list_result.message)

    forceload = server_smoke.rcon(name, "forceload add 0 0 15 15")
    report.record(suite="server", name="server:forceload-chunks", status="passed" if forceload.ok else "failed", category="world-loading", reason=forceload.message)

    confirmed_sentinels = _server_mod_command_checks(report, name)

    save_result = server_smoke.rcon(name, "save-all flush")
    report.record(suite="server", name="server:save-all", status="passed" if save_result.ok else "failed", category="server-health", reason=save_result.message)

    started = time.monotonic()
    stop_result = server_smoke.stop_gracefully(name, timeout_seconds=ctx.timeout("server_stop", 120), log_path=evidence / "stop-1.log")
    report.record(suite="server", name="server:clean-shutdown", status="passed" if stop_result.ok else "failed", category="server-health", duration_seconds=time.monotonic() - started, reason=stop_result.message)
    if not stop_result.ok:
        return

    # Re-use the SAME container (same data dir) rather than a fresh `docker
    # run` so the second boot genuinely reuses the persisted /data volume.
    started = time.monotonic()
    resume = server_smoke.restart_existing_container(name, log_path=evidence / "restart.log")
    report.record(suite="server", name="server:restart-container", status="passed" if resume.returncode == 0 else "failed", category="server-startup", duration_seconds=time.monotonic() - started, reason=resume.stdout_tail if resume.returncode != 0 else "")
    if resume.returncode != 0:
        return

    second_boot_since = server_smoke.container_started_at(name)
    started = time.monotonic()
    health2 = server_smoke.wait_for_healthy_or_done(
        name, timeout_seconds=ctx.timeout("server_health", 900), log_path=evidence / "startup-2.log", since=second_boot_since
    )
    report.record(suite="server", name="server:second-startup-healthy", status="passed" if health2.ok else "failed", category="server-health", duration_seconds=time.monotonic() - started, reason=health2.message)
    if not health2.ok:
        return

    _verify_persistence(report, name, confirmed_sentinels)

    server_smoke.stop_gracefully(name, timeout_seconds=ctx.timeout("server_stop", 120), log_path=evidence / "stop-2.log")


def _verify_persistence(report: Report, name: str, confirmed_sentinels: list[str]) -> None:
    """Re-queries the exact scoreboard sentinels _server_mod_command_checks
    set before the restart -- scoreboard values are saved into the world
    (data/scoreboard.dat) alongside the blocks that were placed, so a match
    here is real evidence the save/restart cycle preserved world state, not
    just that RCON is reachable again.
    """
    if not confirmed_sentinels:
        report.record(
            suite="server", name="server:persistence-after-restart", status="skipped", category="server-health",
            reason="no command-smoke sentinels were confirmed before the restart to check persistence of",
        )
        return
    mismatches = []
    for sentinel in confirmed_sentinels:
        ok, value, raw = server_smoke.scoreboard_get(name, sentinel, SCOREBOARD_OBJECTIVE)
        if not (ok and value == 1):
            mismatches.append(f"{sentinel}: {raw!r}")
    report.record(
        suite="server",
        name=f"server:persistence-after-restart ({len(confirmed_sentinels)} sentinels)",
        status="passed" if not mismatches else "failed",
        category="server-health",
        reason="" if not mismatches else f"scoreboard sentinel(s) did not survive the restart: {mismatches}",
        remediation=None if not mismatches else "World save/load did not preserve state that should persist -- inspect stop-1.log/startup-2.log.",
    )


SCOREBOARD_OBJECTIVE = "aeronautica"


def _server_mod_command_checks(report: Report, name: str) -> list[str]:
    """Places each block and verifies it via a scoreboard sentinel rather
    than `say`/chat output: a real run of this suite (2026-07-30) found that
    `execute if block ... run say SENTINEL`'s broadcast reliably reaches the
    server log but does NOT reliably come back in that same rcon-cli
    invocation's own response text, which would have silently passed a
    command that never actually matched the block. `scoreboard players get`
    returns its value directly and synchronously through RCON. Returns the
    sentinel names that were confirmed, so the persistence check after
    restart can re-query exactly those.
    """
    # Real registry IDs verified from the shipped jars -- see
    # tests/registry-facts.json / extract_registry_facts.py. Coordinates
    # all stay within block (0,0)-(15,15), the single chunk force-loaded by
    # the caller just before this runs.
    checks = [
        ("create", "create:cogwheel", 0, 100, 0),
        ("ad_astra", "ad_astra:steel_block", 5, 100, 0),
        ("vs_eureka", "vs_eureka:anchor", 0, 100, 5),
        ("vs_clockwork", "vs_clockwork:propeller_bearing", 5, 100, 5),
        ("amendments", "amendments:wall_lantern", 10, 100, 0),
    ]
    server_smoke.ensure_scoreboard_objective(name, SCOREBOARD_OBJECTIVE)
    confirmed: list[str] = []
    for mod_key, block_id, x, y, z in checks:
        sentinel = f"AERONAUTICA_OK_{mod_key.upper()}"
        server_smoke.scoreboard_set(name, sentinel, SCOREBOARD_OBJECTIVE, 0)
        place = server_smoke.rcon(name, f"setblock {x} {y} {z} {block_id}")
        server_smoke.rcon(name, f"execute if block {x} {y} {z} {block_id} run scoreboard players set {sentinel} {SCOREBOARD_OBJECTIVE} 1")
        got_ok, value, raw = server_smoke.scoreboard_get(name, sentinel, SCOREBOARD_OBJECTIVE)
        ok = place.ok and got_ok and value == 1
        report.record(
            suite="server",
            name=f"server:command-smoke ({block_id})",
            status="passed" if ok else "failed",
            category="server-health",
            reason="" if ok else f"place={place.message!r} scoreboard_get={raw!r}",
            command=f"setblock {x} {y} {z} {block_id}",
        )
        if ok:
            confirmed.append(sentinel)
    return confirmed


# --------------------------------------------------------------------------
# gametest
# --------------------------------------------------------------------------


def run_gametest(report: Report, ctx: RunContext) -> None:
    if not _preflight(report, ctx, "gametest", ["java", "network"]):
        return

    evidence = ctx.evidence_dir("gametest")
    started = time.monotonic()
    stage_result = gametest_runner.stage_jars(timeout_seconds=ctx.timeout("gametest_stage", 900), log_path=evidence / "stage-jars.log")
    report.record(
        suite="gametest", name="gametest:stage-mod-jars", status="passed" if stage_result.returncode == 0 else "failed",
        category="gametest", duration_seconds=time.monotonic() - started,
        reason="" if stage_result.returncode == 0 else stage_result.stdout_tail,
    )
    if stage_result.returncode != 0:
        return

    started = time.monotonic()
    outcome = gametest_runner.run_gametest_server(timeout_seconds=ctx.timeout("gametest_run", 3600), log_path=evidence / "gradlew-run.log")
    report.record(
        suite="gametest",
        name=f"gametest:run-game-test-server ({len(outcome.discovered_tests)} tests discovered)",
        status="passed" if outcome.ok else "failed",
        category="gametest",
        duration_seconds=time.monotonic() - started,
        reason=outcome.message,
        command="gradlew runGameTestServer",
        evidence=[str(outcome.log_path)] if outcome.log_path else [],
        remediation=None if outcome.ok else "Inspect the Gradle log; see TESTING.md 'How to reproduce a GitHub failure locally'.",
    )


# --------------------------------------------------------------------------
# worldgen
# --------------------------------------------------------------------------


def run_worldgen(report: Report, ctx: RunContext, *, radius: int = 50) -> None:
    if not _preflight(report, ctx, "worldgen", ["docker"]):
        return

    mrpacks = sorted(paths.RELEASES_PATH.glob("*.mrpack")) if paths.RELEASES_PATH.exists() else []
    if not mrpacks:
        report.record(suite="worldgen", name="worldgen:mrpack-available", status="failed", category="prerequisite", reason="no built .mrpack -- run the `artifact` suite first")
        return
    mrpack_path = mrpacks[-1]

    name = server_smoke.container_name("worldgen")
    data_dir = ctx.workdir.new("worldgen-data")
    evidence = ctx.evidence_dir("worldgen")

    start_result = server_smoke.start_container(name=name, mrpack_path=mrpack_path, data_dir=data_dir, log_path=evidence / "docker-run.log")
    if start_result.returncode != 0:
        report.record(suite="worldgen", name="worldgen:start-container", status="failed", category="server-startup", reason=start_result.stdout_tail)
        return

    try:
        first_boot_since = server_smoke.container_started_at(name)
        health = server_smoke.wait_for_healthy_or_done(
            name, timeout_seconds=ctx.timeout("server_health", 900), log_path=evidence / "startup.log", since=first_boot_since
        )
        report.record(suite="worldgen", name="worldgen:reach-healthy", status="passed" if health.ok else "failed", category="server-health", reason=health.message)
        if not health.ok:
            return

        server_smoke.stop_gracefully(name, timeout_seconds=120)
        try:
            placed = worldgen_perf.inject_test_tools(data_dir, ctx.cache_dir)
            report.record(suite="worldgen", name="worldgen:inject-test-tools", status="passed", category="worldgen", evidence=placed)
        except Exception as exc:  # noqa: BLE001 - report, never crash the suite
            report.record(suite="worldgen", name="worldgen:inject-test-tools", status="failed", category="worldgen", reason=str(exc))
            return
        server_smoke.restart_existing_container(name)
        second_boot_since = server_smoke.container_started_at(name)
        health2 = server_smoke.wait_for_healthy_or_done(
            name, timeout_seconds=ctx.timeout("server_health", 900), log_path=evidence / "startup-2.log", since=second_boot_since
        )
        report.record(suite="worldgen", name="worldgen:reach-healthy-with-tools", status="passed" if health2.ok else "failed", category="server-health", reason=health2.message)
        if not health2.ok:
            return

        started = time.monotonic()
        worldgen_outcome = worldgen_perf.run_worldgen(name, radius=radius, timeout_seconds=ctx.timeout("worldgen_run", 1800))
        report.record(
            suite="worldgen",
            name=f"worldgen:generate-radius-{radius}",
            status="passed" if worldgen_outcome.ok else "failed",
            category="worldgen",
            duration_seconds=time.monotonic() - started,
            reason=worldgen_outcome.message,
            evidence=[f"chunks_processed={worldgen_outcome.chunks_processed}"] if worldgen_outcome.chunks_processed else [],
        )

        perf_outcome = worldgen_perf.capture_performance_snapshot(name, evidence)
        report.record(
            suite="worldgen", name="worldgen:performance-snapshot", status="passed" if perf_outcome.ok else "failed",
            category="performance", reason=perf_outcome.message, evidence=perf_outcome.evidence or [],
        )
    finally:
        server_smoke.collect_evidence(name, evidence)
        server_smoke.copy_data_logs(data_dir, evidence)
        server_smoke.remove_container(name)


# --------------------------------------------------------------------------
# full
# --------------------------------------------------------------------------

ALL_SUITES: dict[str, Callable[[Report, RunContext], None]] = {
    "prereqs": run_prereqs,
    "fast": run_fast,
    "artifact": run_artifact,
    "client": run_client,
    "server": run_server,
    "gametest": run_gametest,
    "worldgen": run_worldgen,
}


def run_full(report: Report, ctx: RunContext, *, worldgen_radius: int = 50) -> None:
    for suite_name in ("prereqs", "fast", "artifact", "client", "server", "gametest"):
        print(f"\n----- full: entering suite '{suite_name}' -----")
        ALL_SUITES[suite_name](report, ctx)
    print("\n----- full: entering suite 'worldgen' -----")
    run_worldgen(report, ctx, radius=worldgen_radius)
