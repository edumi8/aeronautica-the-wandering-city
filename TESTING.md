# Testing Aeronautica: The Wandering City

One Python implementation drives every suite, locally and in GitHub Actions.
There is no separate CI-only test logic: `scripts/test_pipeline.py` is what
both your terminal and every workflow job invoke.

```
python scripts/test_pipeline.py <prereqs|fast|artifact|client|server|gametest|worldgen|full>
```

Platform wrappers exist so you never have to remember the Python invocation:

```bash
./scripts/test.sh fast
```

```powershell
.\scripts\test.ps1 fast
```

Both wrappers just locate a Python 3.11+ interpreter and exec
`scripts/test_pipeline.py "$@"`, forwarding the real exit code. If you're on
Windows without Git Bash, use `test.ps1`; if you're in WSL/Linux/macOS, use
`test.sh`.

## Flags (all suites)

| Flag | Effect |
|---|---|
| `--help` | Full option reference. |
| `--allow-missing-runtime` | A missing prerequisite (Docker/Java/Xvfb/...) makes the affected suite **skip** instead of **fail**. Without it, `full` and individual suites fail loudly and specifically -- they never silently skip a required test. |
| `--keep-workdir` | Do not delete temporary instance/build directories on exit. Prints their paths so you can inspect a failure by hand. |
| `--output-dir DIR` | Where `report.json`, `junit.xml`, and per-suite evidence subdirectories go. Default: `test-results/`. |
| `--cache-dir DIR` | Content-addressed download cache shared across suites (default: `.cache/aeronautica-test-downloads/`, gitignored). Reused between `artifact`, `client`, `server`, `gametest`, `worldgen` so a full local `full` run doesn't re-download ~150 MB of mods five times. |
| `--json-report` | Also print the full JSON report to stdout at the end. |
| `--timeout-multiplier N` | Scale every suite's default timeouts (e.g. `2.0` doubles them) -- useful on slower machines/CI runners. |
| `--skip-build` | `artifact` suite only. Skip building; validate whatever is already in `releases/`. Used by CI's per-OS installer jobs after downloading the build job's artifact -- see "GitHub workflow structure" below. Not normally needed locally. |
| `--worldgen-radius N` | `worldgen`/`full` only. Default 50 (CI-sized); the nightly workflow passes a larger radius. |

## Exit codes

Stable and documented (`scripts/aeronautica_testing/exit_codes.py`):

| Code | Meaning |
|---|---|
| 0 | Everything that ran passed. |
| 1 | At least one test/phase failed. |
| 2 | Bad CLI usage (unknown suite, bad flag). |
| 3 | A required prerequisite was missing and `--allow-missing-runtime` was not passed. |
| 4 | An unhandled exception occurred inside the pipeline itself -- always distinct from exit 0, so a pipeline crash can never be mistaken for success. |
| 130 | Interrupted (Ctrl-C). |

## The suites

| Suite | What it proves | Needs | Typical duration |
|---|---|---|---|
| `prereqs` | Prints detected vs. required versions for every tool any suite might need, with exact remediation. Always exits 0/3 based on whether *mandatory* tools (Python, Java) are present; everything else is informational. | nothing | a few seconds |
| `fast` | `python -m compileall` on the pipeline itself, manifest/compat-matrix structural checks against the already-resolved `modpack/manifest.json` (no network), `pytest tests/unit`, and a structural check of whatever `.mrpack` already exists in `releases/` if any. This is the suite to run on every save. | nothing (network-free) | a few seconds |
| `artifact` | Builds the pack for real (`scripts/validate.py --build --verify-downloads`), then: ZIP/path-security/duplicate/hash-syntax/env validation (Phase 3's full checklist), downloads and re-verifies every declared file's actual size/SHA-1/SHA-512, batch-verifies Modrinth-hosted files against `POST /v2/version_files`, checks `SHA256SUMS`, runs an **independent** install via `minecraft-launcher-lib` and diffs the resulting file tree against the index, and builds the pack **twice more** into isolated temp dirs to confirm byte-identical SHA-256 output. | network | 3-8 min (mod downloads) |
| `client` | Installs the exact Forge `1.20.1-47.4.10` client profile via Forge's own installer, verifies that version JSON before ever launching, stages the built `.mrpack`'s mods/overrides via the same independent installer as `artifact`, stages the MC-Runtime-Test helper mod (dev-instance only, never released), and drives HeadlessMC through a real headless launch: join/create a singleplayer world, wait, exit; then a second launch to check the same world reopens. | Java 17, network, Linux+Xvfb (native or via `docker/client-test.Dockerfile`) | 5-15 min |
| `server` | Boots the actual local `.mrpack` in `itzg/minecraft-server:java17` (Modrinth-modpack mode, the image's own exclude/include heuristics disabled so the pack's own `env.client`/`env.server` metadata is what's actually tested), confirms Java 17 / Minecraft 1.20.1 / Forge 47.4.10 from the container, RCON `list`, force-loads a chunk, runs sentinel-verified placement checks against real registry IDs (Create/Ad Astra/Eureka/Clockwork/Amendments), saves, stops cleanly, restarts from the same data directory, and confirms persistence. | Docker | 5-10 min |
| `gametest` | Stages every production mod jar the pack resolves to, builds the `tests/gametest/` ForgeGradle userdev project, and runs `gradlew runGameTestServer`. Fails loudly (not silently) if zero tests were discovered. **Currently blocked -- see "Known limitations".** | Java 17, network, ~2 GB disk for Gradle/ForgeGradle caches | 3-40 min (first run downloads/decompiles; later runs are fast) |
| `worldgen` | Boots a server, injects test-only pinned Chunky + spark (never the release pack), pre-generates a fixed-seed radius around spawn, and captures a local (never uploaded) TPS/health snapshot. | Docker | 5-30 min depending on radius |
| `full` | Every suite above, in order. A suite that hits a missing required prerequisite **fails** the run unless you pass `--allow-missing-runtime`, in which case it's recorded as `skipped` with the exact remediation instead. | everything above | 20-60+ min |

## Prerequisites

Run `python scripts/test_pipeline.py prereqs` for a live report. Summary:

| Tool | Required for | Notes |
|---|---|---|
| Python 3.11+ | everything | you're already running it |
| Java 17 (exact major) | `client`, `gametest` | [Eclipse Temurin 17](https://adoptium.net/temurin/releases/?version=17) |
| Docker Desktop/Engine | `server`, `worldgen` | daemon must be reachable, not just the CLI installed |
| Network (api.modrinth.com, cdn.modrinth.com, github.com, files/maven.minecraftforge.net) | `artifact`, `client`, `server`, `worldgen` | no credentials needed anywhere |
| Xvfb + software OpenGL | `client` (native Linux route) | `sudo apt-get install xvfb mesa-utils libgl1-mesa-dri`; on Windows/macOS use the Docker route instead (`docker/client-test.Dockerfile`) |
| ~10 GB free disk | `artifact`/`client`/`server`/`gametest`/`worldgen` | Gradle/ForgeGradle caches and Docker images are the big consumers |
| 8 GB+ RAM | `client`/`server`/`gametest`/`worldgen` | matches the README's own system requirements |

Nothing here is installed automatically and nothing requires administrator
rights beyond what Docker Desktop itself needs.

## Local Windows / WSL / Linux behavior

- **Windows**: `prereqs` detects WSL2 and Docker Desktop separately. `server`
  and `worldgen` just need Docker Desktop running (Linux containers mode,
  the default). `client` has no reliable native-Windows headless-GL route,
  so it runs via `docker/client-test.Dockerfile` (built automatically) --
  or, if you don't have Docker, from WSL directly:
  ```bash
  wsl -d Ubuntu -- bash -c 'sudo apt-get update && sudo apt-get install -y xvfb mesa-utils libgl1-mesa-dri && cd /mnt/d/projects/modpack/aeronautica-the-wandering-city && python3 scripts/test_pipeline.py client'
  ```
  Adjust the `/mnt/...` path to wherever your checkout is mounted.
- **WSL/Linux**: everything runs natively; install `xvfb` for `client`.
- **macOS**: `server`/`worldgen`/`artifact`/`gametest`/`fast`/`prereqs` work
  as on Linux. `client` has no native macOS headless route documented here;
  use the Docker route.
- An interactive Prism Launcher / PollyMC smoke test remains available and
  documented as a manual step -- see `docs/RELEASE_TEST_CHECKLIST.md`. This
  pipeline does not weaken or replace the GitHub Actions `client` job just
  because a given local machine's GUI automation would be fragile.

## GitHub Actions

- **`ci.yml`** -- push to `main` and every pull request. Jobs: Python unit
  tests, build + full static/download/hash/reproducible-build validation,
  independent install on Ubuntu, independent install on Windows, Java 17
  client smoke, Java 17 server smoke. The build job uploads the exact
  `.mrpack`/manual zip/`SHA256SUMS` it produced as a workflow artifact;
  every later job downloads that same artifact instead of rebuilding, so
  what's tested is provably what was built (reproducibility itself is
  covered separately, deliberately, inside the build job).
- **`nightly.yml`** -- daily schedule, `workflow_dispatch`, and pushes of
  `v*` tags. Calls `ci.yml` as a reusable workflow (so nightly never
  re-implements PR logic), then adds Forge GameTests, worldgen +
  performance capture (larger radius than CI), and a **non-blocking**
  (`continue-on-error: true`) Java 21 compatibility experiment that never
  gates the run and never replaces the Java 17 job.
- **`build.yml`** -- tag pushes and manual dispatch only. Builds and
  attaches release artifacts to the GitHub Release. Never runs as part of
  testing and never publishes a Modrinth version.

All three: `permissions: contents: read` by default (`build.yml` elevates
to `contents: write` on exactly the one job/step that attaches release
assets), a concurrency group that cancels superseded PR runs, per-job
timeouts, `actions/cache` keyed by `hashFiles('modpack/manifest.json')` +
OS + MC/Forge/Java version, first-party actions pinned to major-version
tags, the one third-party action (`softprops/action-gh-release`) pinned to
a full commit SHA with a comment naming the release. No GitHub Release or
Modrinth version is ever published by a *testing* workflow, and the
already-published Modrinth project is never the thing under test -- every
job downloads/builds the local artifact.

## Reproducing a GitHub Actions failure locally

1. Find the failing job's name in the Actions run (e.g. "Java 17 dedicated
   server smoke test (Docker)").
2. Match it to a suite using the table above (that job runs
   `python scripts/test_pipeline.py server`).
3. Download the job's `test-results-*` artifact for the exact
   `report.json`/`junit.xml`/logs from that run, or just run the same
   command locally:
   ```bash
   python scripts/test_pipeline.py server --output-dir test-results --keep-workdir
   ```
4. `--keep-workdir` retains the temporary instance/container data directory
   so you can inspect it after a failure; the printed evidence paths in the
   failed `Result` point at the exact log/crash-report files.

## Logs and artifact locations

- `test-results/report.json` -- machine-readable, one `Result` per
  phase (suite, name, status, category, duration, reason, command,
  evidence paths, remediation).
- `test-results/junit.xml` -- same data in JUnit form for CI test-report UIs.
- `test-results/evidence/<suite>/` -- raw logs, `docker inspect` dumps,
  installed-file inventories, spark snapshots, screenshots.
- `.cache/aeronautica-test-downloads/` -- gitignored, content-addressed
  download cache shared across suites.

## How to add a new mod compatibility rule

Every compatibility rule lives in one place:
`scripts/aeronautica_testing/compat.py`. Both `scripts/validate.py` (the
build-time gate) and the `fast`/`artifact` test suites import from it, so
there is exactly one rule set, never two that can drift.

1. Write a function `(versions: dict[str, str], pins: dict[str, str | None]) -> str | None`
   that returns an error message (or `None` if satisfied). `versions` maps
   every resolved mod's slug to its `version_number`; `pins` maps slugs that
   carry an explicit `"version"` in `manifest.json`'s source `mods` array.
2. Wrap it in a `CompatRule(name=..., description=..., check=...)` and
   append it to `CORE_RULES`.
3. Add a test case to `tests/unit/test_compat.py` covering both the
   violation and the clean case.
4. Run `python scripts/test_pipeline.py fast` -- the new rule is now
   enforced by the build (`scripts/validate.py`) and by CI automatically.

## How to add a GameTest

1. Add a `public static void` method to an existing class under
   `tests/gametest/src/main/java/com/aeronautica/gametest/tests/`, or add a
   new class annotated `@GameTestHolder(AeronauticaGameTestMod.MOD_ID)` +
   `@PrefixGameTestTemplate(false)`.
2. Annotate the method `@GameTest(template = "empty_platform", setupTicks = ..., timeoutTicks = ...)`
   -- every test in this suite shares the one generic platform structure
   (`tests/gametest/src/main/resources/data/aeronauticagametest/structures/empty_platform.nbt`,
   generated by `tests/gametest/tools/generate_structures.py`; regenerate
   only if you deliberately change its size) and builds its actual scenario
   in code via `helper.setBlock(...)`.
3. Prefer `ForgeRegistries.BLOCKS`/`ITEMS` lookups by `ResourceLocation`
   (via `TestSupport.requireBlock`/`requireItem`) over importing a
   third-party mod's internal classes -- see `RegistryFacts.java`
   (mechanically generated, never hand-typed, from
   `tests/registry-facts.json`; regenerate both with
   `python scripts/aeronautica_testing/tools/extract_registry_facts.py`
   then `python tests/gametest/tools/generate_registry_facts_java.py` after
   bumping a pinned mod version).
4. Add the new method's exact name to `KNOWN_TEST_METHODS` in
   `scripts/aeronautica_testing/gametest_runner.py` -- this is how the
   pipeline enforces "fail if zero/too-few tests were discovered" without
   depending on parsing Forge's own log format precisely.
5. Run `python tests/gametest/tools/stage_jars.py` once, then
   `cd tests/gametest && ./gradlew runGameTestServer` (or `gradlew.bat`).

## How to update pinned test tools

- **minecraft-launcher-lib / pytest**: bump the pin in `tests/requirements.txt`,
  run `python -m pip install -r tests/requirements.txt`, run `fast` and
  `artifact` locally.
- **Chunky / spark**: re-resolve via the Modrinth API (never guess a
  version/hash) and update `tests/worldgen/tools-lock.json`:
  ```bash
  python - <<'PY'
  import json, urllib.request, urllib.parse
  for slug, pid in [("chunky", "fALzjamp"), ("spark", "l6YH9Als")]:
      q = urllib.parse.urlencode({"loaders": json.dumps(["forge"]), "game_versions": json.dumps(["1.20.1"])})
      req = urllib.request.Request(f"https://api.modrinth.com/v2/project/{pid}/version?{q}",
                                    headers={"User-Agent": "manual-lock-refresh/1.0"})
      print(slug, json.load(urllib.request.urlopen(req))[0]["version_number"])
  PY
  ```
- **HeadlessMC / MC-Runtime-Test**: bump `HEADLESSMC_VERSION` /
  `MC_RUNTIME_TEST_VERSION` in `scripts/aeronautica_testing/client_smoke.py`
  after confirming the new release publishes a `mc-runtime-test-1.20.1-<ver>-lexforge-release.jar`
  asset on its GitHub Releases page.
- **Gradle wrapper**: `cd tests/gametest && gradle wrapper --gradle-version <new>`
  if you have a system Gradle, or replace `gradle/wrapper/gradle-wrapper.jar`
  from `https://raw.githubusercontent.com/gradle/gradle/v<version>/gradle/wrapper/gradle-wrapper.jar`
  and update `gradle-wrapper.properties`' `distributionSha256Sum` from
  `https://services.gradle.org/distributions/gradle-<version>-bin.zip.sha256`.

## Known limitations

- **Forge GameTest execution is currently blocked in this repository's dev
  environment.** `tests/gametest/` compiles cleanly (all 10 tests, verified
  with `javac`/Gradle) and the Gradle project itself is fully wired
  (ForgeGradle downloads/decompiles/launches correctly), but
  `gradlew runGameTestServer` currently fails before any test executes.
  Root cause, confirmed by direct investigation (not guessed): several
  production mods' `MinecraftServer`-targeting Mixins (`modernfix`,
  `kubejs`, and critically **`valkyrienskies`**, a mod this suite needs)
  fail with `@Shadow ... was not located in the target class
  net.minecraft.server.MinecraftServer` -- their Mixin refmap's SRG names
  are not being remapped to this ForgeGradle userdev run's official-mapped
  class. The same jars install and run correctly through a normal launcher
  (see the README's alpha.2 smoke-test note), and the Docker dedicated
  server test uses production Forge, not userdev, so it is unaffected --
  this is specific to loading many complex third-party production jars
  inside a ForgeGradle *dev* environment, not a real mod-compatibility
  problem. `modernfix` and `kubejs` are excluded from GameTest staging only
  (`tests/gametest/tools/stage_jars.py`, `GAMETEST_DEV_ENV_UNSTABLE_SLUGS`)
  since neither is exercised by any test; Valkyrien Skies cannot be
  excluded the same way, so the suite is implemented and ready but not
  currently green. Next diagnostic step for whoever picks this up: compare
  against a from-scratch `net.minecraftforge.gradle` userdev setup with
  *only* `valkyrienskies` staged (no other mods) to confirm whether the
  refmap-remap failure is triggered by mod interaction or reproduces in
  isolation; if it reproduces alone, file upstream against ForgeGradle with
  the exact stack trace in `tests/gametest/gradle-run-*.log`.
- **`client` suite screenshot-on-failure** requires `xwd` + ImageMagick's
  `convert`, both provided by `docker/client-test.Dockerfile`; a native
  Linux run without those installed simply omits the screenshot (not a
  failure).
- **Reflection in `CreateKineticTests`**: reading a live kinetic rotation
  speed uses reflection against Create's `KineticBlockEntity#getSpeed()`,
  which is public but not covered by any stability contract this
  repository controls. If it's ever renamed, the test degrades to a
  documented, weaker (presence + no-crash-after-ticking) assertion instead
  of failing outright -- see the comment in that file.
- **Worldgen/spark command syntax** (Chunky's `radius`/`center`/`world`/
  `start`/`query`, spark's `tps`/`health`) follows each tool's long-stable,
  well-documented admin-command surface, but has not been exercised against
  a live server in this session -- treat the first real nightly run as the
  actual verification and adjust `worldgen_perf.py`'s regex-based
  completion/progress parsing if the exact wording differs.
- **Second-launch "same world reopened" check** (`client` suite) is
  best-effort: it compares the `saves/` directory before/after a second
  HeadlessMC launch and reports honestly (`passed`/`skipped` with a clear
  reason) rather than assuming success if MC-Runtime-Test turns out to
  create a fresh world per run.

## Why Java 17 and Forge 47.4.10 are pinned

Forge 47.4.10 is the exact build this pack's core physics stack (Create,
Clockwork, Valkyrien Skies, Eureka) was integration-tested against --
`modpack/manifest.json` and every suite in this pipeline hard-fail on any
other Forge build rather than silently testing "whatever's current". Java
17 is [Forge's own required runtime for the 1.20.x line](https://github.com/MinecraftForge/MinecraftForge#required-java-versions).
A Java 21 run exists (see `nightly.yml`) purely as a forward-looking,
non-blocking experiment; it can never make the main workflow green when
Java 17 fails, and it never changes what ships.

## Why arbitrary `ERROR` log lines are not automatic failures

Forge modpacks routinely log recoverable, non-fatal `ERROR`-level lines
(a missing optional integration, a datapack probe for a resource that
doesn't exist, a deprecation notice from a library). Treating every
`ERROR` line as a hard failure produces a suite that is either constantly
red for reasons nobody investigates, or gets "fixed" by someone adding an
overly broad regex that quietly swallows a real crash. Instead, every
suite here fails on **specific, named, fatal signatures**
(`ModLoadingException`, `Failed to complete lifecycle event`,
`Exception in server tick loop`, `OutOfMemoryError`,
`Minecraft Crash Report`, unexpected container exit, health-check timeout,
RCON unavailability, failed clean shutdown) plus a short, explicitly
documented, per-line known-benign allowlist
(`server_smoke.KNOWN_BENIGN_LOG_SUBSTRINGS`) that must never grow into a
broad pattern. If you hit a new benign `ERROR` line, add its literal
substring there with a comment explaining what produces it -- do not widen
an existing regex.

## Automated vs. manual coverage

See the coverage matrix in `docs/RELEASE_TEST_CHECKLIST.md` for the full
per-feature breakdown. In short: static validation, artifact structure,
downloads/hashes, independent install, client startup + world/chunk
loading, server startup/health/RCON/persistence, and (once unblocked)
GameTest gameplay-logic assertions are automated. Full manual-launcher
import (Modrinth App / Prism / PollyMC), extended multi-hour play,
multiplayer with real second players, and subjective rendering/shader
quality remain manual -- see the checklist for the exact steps.
