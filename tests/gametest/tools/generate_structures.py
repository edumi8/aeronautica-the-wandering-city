#!/usr/bin/env python3
"""Generate the shared GameTest structure template as a real, well-formed
Minecraft structure NBT file, written directly against the documented
binary NBT format (gzip-compressed big-endian tag stream) and the
Minecraft "structure" NBT schema (DataVersion/size/palette/blocks/entities).

Why generate instead of hand-author in-game: authoring a .nbt structure
normally means opening a dev client, placing a structure block, and saving
-- there is no interactive Minecraft session available in this pipeline's
authoring environment. Every GameTest in this project therefore shares ONE
small, generic 5x4x5 stone-floored platform (stone at y=0, air y=1..3) and
builds its actual test scenario at runtime via GameTestHelper#setBlock, which
is also the idiomatic way Forge/vanilla's own GameTest suites are written
(structures are rarely more than a bounding platform; the interesting state
is set up in code so it stays readable and diffable).

Run: python tests/gametest/tools/generate_structures.py
Regenerate only if you deliberately change SIZE_X/Y/Z below.
"""
from __future__ import annotations

import gzip
import io
import struct
from pathlib import Path

DATA_VERSION = 3465  # Minecraft 1.20.1, confirmed via minecraft.wiki "Data version"
SIZE_X, SIZE_Y, SIZE_Z = 5, 4, 5
OUTPUT_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "main"
    / "resources"
    / "data"
    / "aeronauticagametest"
    / "structures"
    / "empty_platform.nbt"
)

TAG_END = 0
TAG_BYTE = 1
TAG_INT = 3
TAG_STRING = 8
TAG_LIST = 9
TAG_COMPOUND = 10


def _string(buf: io.BytesIO, value: str) -> None:
    data = value.encode("utf-8")
    buf.write(struct.pack(">H", len(data)))
    buf.write(data)


def _named_header(buf: io.BytesIO, tag_type: int, name: str) -> None:
    buf.write(struct.pack(">b", tag_type))
    _string(buf, name)


def _int_tag(buf: io.BytesIO, name: str, value: int) -> None:
    _named_header(buf, TAG_INT, name)
    buf.write(struct.pack(">i", value))


def _int_list_payload(buf: io.BytesIO, values: list[int]) -> None:
    buf.write(struct.pack(">b", TAG_INT))
    buf.write(struct.pack(">i", len(values)))
    for value in values:
        buf.write(struct.pack(">i", value))


def build_structure_nbt() -> bytes:
    buf = io.BytesIO()
    _named_header(buf, TAG_COMPOUND, "")  # unnamed root compound

    _int_tag(buf, "DataVersion", DATA_VERSION)

    _named_header(buf, TAG_LIST, "size")
    _int_list_payload(buf, [SIZE_X, SIZE_Y, SIZE_Z])

    # palette: [0]=air [1]=stone
    _named_header(buf, TAG_LIST, "palette")
    buf.write(struct.pack(">b", TAG_COMPOUND))
    buf.write(struct.pack(">i", 2))
    for block_name in ("minecraft:air", "minecraft:stone"):
        _named_header(buf, TAG_STRING, "Name")
        _string(buf, block_name)
        buf.write(struct.pack(">b", TAG_END))  # close each palette entry compound

    # blocks: explicit entry for every cell in the volume (matches a
    # structure-block save with "include air" enabled).
    entries: list[tuple[int, int, int, int]] = []
    for x in range(SIZE_X):
        for y in range(SIZE_Y):
            for z in range(SIZE_Z):
                state = 1 if y == 0 else 0  # stone floor, air above
                entries.append((x, y, z, state))

    _named_header(buf, TAG_LIST, "blocks")
    buf.write(struct.pack(">b", TAG_COMPOUND))
    buf.write(struct.pack(">i", len(entries)))
    for x, y, z, state in entries:
        _named_header(buf, TAG_LIST, "pos")
        _int_list_payload(buf, [x, y, z])
        _int_tag(buf, "state", state)
        buf.write(struct.pack(">b", TAG_END))  # close this block-entry compound

    # entities: empty list of compounds
    _named_header(buf, TAG_LIST, "entities")
    buf.write(struct.pack(">b", TAG_COMPOUND))
    buf.write(struct.pack(">i", 0))

    buf.write(struct.pack(">b", TAG_END))  # close root compound
    return buf.getvalue()


def main() -> int:
    raw = build_structure_nbt()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_bytes(gzip.compress(raw, mtime=0))
    print(f"wrote {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size} bytes, {len(raw)} raw)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
