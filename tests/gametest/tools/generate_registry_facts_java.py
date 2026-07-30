#!/usr/bin/env python3
"""Regenerate RegistryFacts.java from tests/registry-facts.json so the Java
GameTest sources and the Python-side facts never drift apart by hand-typo.

Run after re-running extract_registry_facts.py:
    python tests/gametest/tools/generate_registry_facts_java.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from aeronautica_testing import paths  # noqa: E402

FACTS_PATH = paths.TESTS_DIR / "registry-facts.json"
OUTPUT_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "main"
    / "java"
    / "com"
    / "aeronautica"
    / "gametest"
    / "RegistryFacts.java"
)

HEADER = """package com.aeronautica.gametest;

import java.util.List;

/**
 * Mechanically generated from tests/registry-facts.json -- do not hand-edit.
 * Regenerate with: python tests/gametest/tools/generate_registry_facts_java.py
 *
 * Every ID below was found verbatim inside the pinned mod jar it names
 * (blockstate/item-model/dimension filenames map 1:1 to registry paths);
 * none were guessed. See scripts/aeronautica_testing/tools/extract_registry_facts.py.
 */
public final class RegistryFacts {
    private RegistryFacts() {}
"""


def java_string_list(name: str, values: list[str]) -> str:
    items = ", ".join(f'"{v}"' for v in values)
    return f"    public static final List<String> {name} = List.of({items});\n"


def main() -> int:
    facts = json.loads(FACTS_PATH.read_text(encoding="utf-8"))
    lines = [HEADER]

    for slug, mod in facts["mods"].items():
        const_prefix = slug.upper().replace("-", "_")
        lines.append(f'    public static final String {const_prefix}_MOD_ID = "{mod["mod_id"]}";\n')
        if mod["curated_blocks"]:
            lines.append(java_string_list(f"{const_prefix}_BLOCKS", mod["curated_blocks"]))
        if mod["curated_items"]:
            lines.append(java_string_list(f"{const_prefix}_ITEMS", mod["curated_items"]))
        if mod["curated_dimensions"]:
            lines.append(java_string_list(f"{const_prefix}_DIMENSIONS", mod["curated_dimensions"]))
        lines.append("\n")

    lines.append("}\n")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text("".join(lines), encoding="utf-8")
    print(f"wrote {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
