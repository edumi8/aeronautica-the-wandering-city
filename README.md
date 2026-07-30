# Aeronautica: The Wandering City

Aeronautica: The Wandering City is a progression-first Minecraft Forge 1.20.1 modpack focused on industrializing a settlement, raising it into the sky, and expanding into space. The pack is built around a guided path of survival, automation, aviation, a moving sky city, electricity, and finally colonization.

> Experimental alpha warning: this is an early, physics-heavy pack. Expect version-sensitive gameplay, ongoing balancing, and occasional compatibility churn while the core progression is still being polished.

## Progression overview

Survival â†’ Create â†’ Steam â†’ Aviation â†’ Moving Sky City â†’ Electricity â†’ Space Program â†’ Colonization

The campaign structure is documented in [overrides/docs/PROGRESSION.md](overrides/docs/PROGRESSION.md) and the operating rules for ships and city movement are documented in [overrides/docs/SHIP-RULES.md](overrides/docs/SHIP-RULES.md).

## Feature highlights

- Create-based industry and automation from the ground up
- Steam-era logistics and rail progression
- Experimental aircraft and airship travel
- A moving sky-city playstyle with physics-sensitive infrastructure
- Supplementaries and Amendments building details for a richer aerial city
- Electricity and advanced industrialization with Create: New Age
- Ad Astra-driven space program and colonization goals
- KubeJS foundation for future progression scripting and tuning

## Installation

### PollyMC

1. Open PollyMC.
2. Choose Add Instance.
3. Select Import.
4. Choose the generated .mrpack file.
5. Wait for installation to finish.
6. Launch with Java 17.

### Prism Launcher

1. Open Prism Launcher.
2. Create a new instance or choose Add Instance.
3. Select Import.
4. Pick the .mrpack file.
5. Allow the instance to install.
6. Launch with Java 17.

### PolyMC

1. Open PolyMC.
2. Choose Add Instance.
3. Select Import.
4. Pick the .mrpack file.
5. Wait for the install to complete.
6. Launch with Java 17.

### Modrinth App

1. Open the Modrinth App.
2. Choose Create Instance or Import.
3. Select the .mrpack file.
4. Wait for installation to finish.
5. Launch with Java 17.

### Manual fallback installation

If you need to install manually, use the generated manual ZIP from the releases folder or run the fallback installer from the repository root:

```powershell
./install.ps1 -InstancePath "C:\Path\To\Your\Instance\.minecraft"
```

```bash
./install.sh "$HOME/.local/share/Instance/.minecraft"
```

The fallback installer resolves Modrinth dependencies, verifies SHA-512 hashes, and writes an instance-local lockfile.

## System requirements

- Minecraft Java Edition 1.20.1 (required)
- Forge 47.4.10 (required)
- Java 17 (required; tested with Eclipse Adoptium 17.0.16)
- 8 GB RAM minimum, 10 GB recommended for multiplayer or very large cities
- A new world is strongly recommended

### Tested core version matrix

- Minecraft 1.20.1
- Forge 47.4.10
- Create 6.0.8
- Clockwork 0.5.6
- Valkyrien Skies 2.4.11
- Eureka 1.6.3
- Java 17

### Smoke-test status

Alpha.2 reached the main menu and loaded a fresh singleplayer world using
PollyMC 8.0, Forge 47.4.10, and Eclipse Adoptium Java 17.0.16. This confirms
basic client startup and world creation only; large airships, long-running
worlds, multiplayer, and dedicated servers remain untested.

## Build instructions

From the repository root, run either:

```powershell
./scripts/build.ps1
```

or:

```bash
./scripts/build.sh
```

The build validates the JSON and repository layout, resolves the Modrinth dependency graph, verifies every downloaded file and SHA-512 checksum, generates the Modrinth index, and writes the .mrpack, manual ZIP, and SHA256SUMS artefacts under releases/.

## Performance recommendations for the moving city

- Use Java 17 (required)
- Use conservative render distance while the city is moving
- Allocate 8 GB RAM minimum; 10 GB is safer for multiplayer or large cities
- Anchor the city before running heavy farms or large multiblock chains
- Test ship blocks and block entities on a small vessel before scaling them up

## Known physics-mod issues

- Valkyrien Skies, Eureka, and Clockwork are intentionally version-sensitive and should not be updated independently
- Large moving structures can be unstable if heavy farms or entity-heavy automation are left active while the city is drifting
- Always back up your world before disassembling, reassembling, or moving a large ship

## Backup recommendations

- Keep regular backups before major ship or city construction
- Use separate worlds for experimental physics-heavy builds
- Prefer a fresh world when testing large-scale city movement

## FTB / Modrinth distribution limitation

The current Modrinth edition intentionally excludes the FTB Quests, FTB Library, and FTB Teams projects because their identifiers currently return 404 from the Modrinth API. They are not left as active entries or TODO objects in the distributable manifest. A future CurseForge edition could revisit these projects if the relevant distribution metadata becomes available.

## Roadmap

The alpha roadmap continues to focus on completing the progression loop, stabilizing core physics-mod interactions, and improving the quality of the city-building and space-colonization experience.

## Contributing

Contributions are welcome. Please see [CONTRIBUTING.md](CONTRIBUTING.md) for the process, compatibility expectations, and validation workflow.

## License

This project is distributed under the MIT License. See [LICENSE](LICENSE) for details.

