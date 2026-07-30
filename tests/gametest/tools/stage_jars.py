#!/usr/bin/env python3
"""Stage the exact production mod JARs from the built pack's resolved
manifest into a gitignored directory so build.gradle can add them as
fg.deobf() dependencies.

This is what Phase 7 means by "load the exact mod JARs installed from the
built .mrpack": the GameTest server boots the real Create/Clockwork/VS/
Eureka/Ad Astra/... jars, not a hand-picked subset and not re-resolved
versions. Run before `gradlew runGameTestServer`:

    python tests/gametest/tools/stage_jars.py

Never commit the contents of .staged-mods/ (see tests/gametest/.gitignore).
"""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from aeronautica_testing import paths  # noqa: E402

STAGED_DIR = Path(__file__).resolve().parents[1] / ".staged-mods"
USER_AGENT = "Aeronautica-Wandering-City-TestPipeline/1.0 (+gametest-jar-staging)"

# Excluded from the GameTest *dev* environment only -- both real routes that
# matter for release correctness (the itzg dedicated-server smoke test and
# the HeadlessMC client smoke test) still load every one of these normally.
#
# 1) env.server == "unsupported": a real dedicated server never loads these
#    either (see modpack/manifest.json), so omitting them from the
#    GameTest *server* run is more representative, not less.
# 2) A short, explicitly-justified list of client/server performance mods
#    whose Mixins patch obfuscated internals of core loader/server classes:
#    these are known to be fragile specifically in ForgeGradle's userdev
#    (SRG-remapped) dev environment even when they work fine in production.
#    Confirmed here (2026-07-30) against Forge 1.20.1-47.4.10 + ForgeGradle
#    6 (Gradle 8.1.1) userdev, official mappings -- every one of the
#    following crashed runGameTestServer with the identical signature
#    (`@Shadow ... was not located in the target class
#    net.minecraft.server.MinecraftServer`, i.e. their MinecraftServer-
#    targeting Mixin's refmap SRG name was not remapped to the official
#    name this userdev run uses):
#      - modernfix   (perf.fix_loop_spin_waiting.MinecraftServerMixin)
#      - kubejs       (common.mixins.json MinecraftServerMixin, m_7038_)
#      - valkyrienskies (server.MixinMinecraftServer, m_129783_)
#    valkyrienskies is a CORE mod this suite needs -- excluding it is not a
#    viable workaround, which means the list below is NOT a complete fix,
#    only removes two known-unnecessary offenders. This is documented as a
#    genuine open limitation of the GameTest *dev environment* in
#    TESTING.md "known limitations" (the same jars install and run
#    correctly in a normal launcher per README's alpha.2 smoke-test note,
#    and the equivalent Docker dedicated-server smoke test uses production
#    Forge, not userdev, so it is unaffected). Do not spend further Gradle
#    cycles re-deriving this without first reading that section.
GAMETEST_DEV_ENV_UNSTABLE_SLUGS = frozenset({"modernfix", "kubejs"})


def _server_relevant(mod: dict) -> bool:
    env = mod.get("env") or {}
    if env.get("server") == "unsupported":
        return False
    if mod["slug"] in GAMETEST_DEV_ENV_UNSTABLE_SLUGS:
        return False
    return True


def main() -> int:
    if not paths.MANIFEST_PATH.exists():
        print(f"ERROR: {paths.MANIFEST_PATH} not found -- run the build first", file=sys.stderr)
        return 1
    manifest = json.loads(paths.MANIFEST_PATH.read_text(encoding="utf-8"))
    resolved = manifest.get("resolved_mods", [])
    if not resolved:
        print("ERROR: manifest.json has no resolved_mods -- run scripts/validate.py first", file=sys.stderr)
        return 1

    skipped = [mod["slug"] for mod in resolved if not _server_relevant(mod)]
    resolved = [mod for mod in resolved if _server_relevant(mod)]
    if skipped:
        print(f"excluding from GameTest staging (see GAMETEST_DEV_ENV_UNSTABLE_SLUGS / env.server): {skipped}")

    STAGED_DIR.mkdir(parents=True, exist_ok=True)
    for existing in STAGED_DIR.glob("*.jar"):
        existing.unlink()

    staged = []
    for mod in resolved:
        cache_path = paths.DEFAULT_CACHE_DIR / f"{mod['sha512']}.jar"
        if not (cache_path.exists() and cache_path.stat().st_size == mod["file_size"]):
            print(f"downloading {mod['slug']} ({mod['filename']}) ...")
            paths.DEFAULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            request = urllib.request.Request(mod["download_url"], headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=120) as response, cache_path.open("wb") as out:
                out.write(response.read())
            digest = hashlib.sha512(cache_path.read_bytes()).hexdigest()
            if digest.lower() != mod["sha512"].lower():
                cache_path.unlink(missing_ok=True)
                print(f"ERROR: sha512 mismatch for {mod['filename']}", file=sys.stderr)
                return 1

        destination = STAGED_DIR / mod["filename"]
        destination.write_bytes(cache_path.read_bytes())
        staged.append(mod["filename"])

    print(f"staged {len(staged)} mod jars into {STAGED_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
