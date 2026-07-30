# Contributing

Thanks for helping improve Aeronautica: The Wandering City.

## Proposing a mod

1. Open an issue describing the mod, the intended progression role, and the expected compatibility target.
2. Note whether the mod is intended for core progression, utility, or quality-of-life play.
3. Mention the Minecraft / Forge version and any known dependency or physics implications.

## Compatibility requirements

- Keep the pack on Minecraft 1.20.1 and Forge 47.4.10 unless a broader pack-level decision is made.
- Preserve the existing core progression and the locked Clockwork / Valkyrien Skies / Eureka compatibility set.
- Avoid introducing unrelated magic or technology mods that would dilute the progression focus.
- If a mod depends on a framework or companion mod, include the full dependency chain rather than adding only the visible feature.

## Running validation

From the repository root, run:

```powershell
./scripts/build.ps1
```

or:

```bash
./scripts/build.sh
```

The build validates the JSON, resolves the Modrinth dependency tree, downloads each selected file, verifies every SHA-512 checksum, and writes the release artefacts under releases/.

## Why versions must be pinned

The pack uses explicit version pins for the core physics compatibility set so that the build remains reproducible and so that a dependency update cannot silently replace the intended Clockwork / Valkyrien Skies / Eureka stack.

## Why core physics mods must not be updated independently

These mods participate in the same physics and movement ecosystem. Updating one without the others can break ship behavior, movement, or city stability. Keep them aligned unless a coordinated compatibility update has been validated.
