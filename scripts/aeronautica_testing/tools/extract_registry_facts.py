#!/usr/bin/env python3
"""Regenerate tests/registry-facts.json from the *actual* pinned mod jars.

Every block/item/dimension ID used by the server smoke test (Phase 6) and the
Forge GameTest project (Phase 7) must be real, not guessed -- see the
repository invariant "do not guess project IDs, versions, URLs, hashes, or
licenses". This tool is how those IDs are verified: it downloads (or reuses
the shared cache of) each target mod's jar as pinned in
modpack/manifest.json, and enumerates real registry names straight out of
its assets/data (blockstate/model/dimension file names map 1:1 to registry
paths for a well-formed mod).

Run this again after bumping a pinned mod version:

    python scripts/aeronautica_testing/tools/extract_registry_facts.py

It only ever *reads* jars and the manifest; it never invents an ID that
doesn't appear in the jar.
"""
from __future__ import annotations

import json
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from aeronautica_testing import paths  # noqa: E402

OUTPUT_PATH = paths.TESTS_DIR / "registry-facts.json"
CACHE_DIR = paths.DEFAULT_CACHE_DIR
USER_AGENT = "Aeronautica-Wandering-City-TestPipeline/1.0 (+registry-fact-extraction)"

# slug -> keyword filters used to keep the output small and thematically
# relevant. The tool still only ever emits paths it actually found in the
# jar; keywords narrow *which* real entries get recorded, they cannot
# fabricate one.
BLOCK_FILTERS: dict[str, list[str]] = {
    "create": ["cogwheel", "shaft", "mechanical_press", "water_wheel", "creative_motor", "gearbox"],
    "create-clockwork": ["propeller_bearing", "combustion_engine", "gas_thruster", "gas_engine"],
    "eureka": ["anchor", "ballast", "engine", "oak_ship_helm", "balloon"],
    "valkyrien-skies": ["test_"],
    "ad-astra": ["launch_pad", "oxygen_distributor", "compressor", "gravity_normalizer", "steel_block"],
    "amendments": ["wall_lantern", "skull_candle", "hanging_flower_pot", "skull_pile"],
    "supplementaries": ["candle_holder", "sign_post", "bellows", "clock_block"],
    "create-new-age": ["basic_motor", "advanced_energiser", "copper_wire_block"],
}
ITEM_FILTERS: dict[str, list[str]] = {
    "valkyrien-skies": ["ship_assembler", "ship_creator", "area_assembler", "ship_remover"],
}
DIMENSION_FILTERS: dict[str, list[str]] = {
    "ad-astra": ["moon", "mars", "mercury", "venus", "glacio"],
}


def _download(mod: dict) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest = CACHE_DIR / f"{mod['sha512']}.jar"
    if dest.exists() and dest.stat().st_size == mod["file_size"]:
        return dest
    request = urllib.request.Request(mod["download_url"], headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response, dest.open("wb") as out:
        out.write(response.read())
    return dest


def _mod_id_from_toml(zf: zipfile.ZipFile) -> str | None:
    for name in zf.namelist():
        if name.endswith("mods.toml"):
            text = zf.read(name).decode("utf-8", errors="replace")
            for line in text.splitlines():
                stripped = line.strip().replace(" ", "")
                if stripped.startswith("modId=") and "forge" not in stripped and "minecraft" not in stripped:
                    return stripped.split("=", 1)[1].strip('"')
    return None


def _lang_block_names(zf: zipfile.ZipFile, mod_id: str) -> set[str] | None:
    """Real, in-game translated names for this mod's blocks, keyed by the
    bare name after ``block.<mod_id>.``. Returns None if the mod ships no
    en_us.json at all (signals "no opinion" to the caller, distinct from an
    empty set).
    """
    try:
        lang = json.loads(zf.read(f"assets/{mod_id}/lang/en_us.json").decode("utf-8"))
    except KeyError:
        return None
    prefix = f"block.{mod_id}."
    return {key[len(prefix) :] for key in lang if key.startswith(prefix)}


def extract(slug: str, mod: dict) -> dict:
    jar_path = _download(mod)
    with zipfile.ZipFile(jar_path) as zf:
        names = zf.namelist()
        mod_id = _mod_id_from_toml(zf) or slug

        blockstates = [n for n in names if f"assets/{mod_id}/blockstates/" in n and n.endswith(".json")]
        item_models = [n for n in names if f"assets/{mod_id}/models/item/" in n and n.endswith(".json")]
        dimensions = [n for n in names if f"data/{mod_id}/dimension/" in n and n.endswith(".json")]
        # A blockstate JSON is a *client rendering asset* and is NOT proof a
        # block is actually registered/placeable -- confirmed the hard way:
        # vs_clockwork ships assets/vs_clockwork/blockstates/propeller_bearing.json
        # (a shared parent asset for its brass_/juryrigged_ variants) with NO
        # registered block behind it, which a real dedicated-server /setblock
        # rejected with "Unknown block type" (CI run 2026-07-30). A block's
        # translated name (assets/<mod_id>/lang/en_us.json, key
        # "block.<mod_id>.<name>") is emitted per registered block by
        # essentially every mod's datagen regardless of loot-table
        # conventions (tried loot_tables/blocks/ first -- too strict, e.g.
        # amendments only datagens loot tables for 2 of its 34 blocks), so
        # cross-check against lang instead wherever the jar has one.
        lang_block_names = _lang_block_names(zf, mod_id)

        def stem(path: str) -> str:
            return path.rsplit("/", 1)[-1][: -len(".json")]

        blocks = sorted({f"{mod_id}:{stem(n)}" for n in blockstates})
        items = sorted({f"{mod_id}:{stem(n)}" for n in item_models})
        dims = sorted({f"{mod_id}:{stem(n)}" for n in dimensions})

        block_kw = BLOCK_FILTERS.get(slug, [])
        item_kw = ITEM_FILTERS.get(slug, [])
        dim_kw = DIMENSION_FILTERS.get(slug, [])

        candidate_blocks = [b for b in blocks if any(k in b for k in block_kw)] if block_kw else []
        if lang_block_names is not None:
            curated_blocks = [b for b in candidate_blocks if b.split(":", 1)[1] in lang_block_names]
        else:
            # No en_us.json at all in this jar -- blockstate presence is the
            # best available signal, same as before this cross-check existed.
            curated_blocks = candidate_blocks

        return {
            "mod_id": mod_id,
            "source_jar_sha512": mod["sha512"],
            "total_blocks_found": len(blocks),
            "total_items_found": len(items),
            "curated_blocks": curated_blocks,
            "curated_items": [i for i in items if any(k in i for k in item_kw)] if item_kw else [],
            "curated_dimensions": [d for d in dims if any(k in d for k in dim_kw)] if dim_kw else [],
        }


def main() -> int:
    manifest = json.loads(paths.MANIFEST_PATH.read_text(encoding="utf-8"))
    resolved_by_slug = {m["slug"]: m for m in manifest.get("resolved_mods", [])}

    target_slugs = sorted(set(BLOCK_FILTERS) | set(ITEM_FILTERS) | set(DIMENSION_FILTERS))
    facts = {
        "_generated_by": "scripts/aeronautica_testing/tools/extract_registry_facts.py",
        "_source": (
            "Enumerated directly from the pinned mod jars in modpack/manifest.json resolved_mods "
            "(sha512-addressed). Every ID below was found verbatim as a blockstate/item-model/dimension "
            "file inside the shipped jar -- none were guessed. curated_blocks is additionally "
            "cross-checked against assets/<mod_id>/lang/en_us.json's block.<mod_id>.<name> keys (when "
            "the jar has one) so a shared/orphaned blockstate asset with no real registered block behind "
            "it (e.g. vs_clockwork:propeller_bearing, a parent asset for its brass_/juryrigged_ variants, "
            "or amendments:skull_candle*) cannot be curated as if it were placeable."
        ),
        "mods": {},
    }
    for slug in target_slugs:
        mod = resolved_by_slug.get(slug)
        if not mod:
            print(f"WARNING: {slug} not found in resolved_mods, skipping", file=sys.stderr)
            continue
        print(f"extracting {slug} ...")
        facts["mods"][slug] = extract(slug, mod)

    OUTPUT_PATH.write_text(json.dumps(facts, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
