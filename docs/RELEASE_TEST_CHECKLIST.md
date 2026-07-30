# Release Test Checklist

Run before publishing a new version. Automated steps are commands; manual
steps are checkboxes. See `TESTING.md` for what each suite proves and how
long it takes.

## 1. Automated (run these first)

```bash
python scripts/test_pipeline.py fast
python scripts/test_pipeline.py artifact
python scripts/test_pipeline.py server        # requires Docker
python scripts/test_pipeline.py client        # requires Java 17 + Xvfb/Docker
python scripts/test_pipeline.py gametest       # requires Java 17; see TESTING.md known limitations
python scripts/test_pipeline.py worldgen --worldgen-radius 200   # optional pre-release, requires Docker
```

Or push a branch and let `ci.yml` run all of the above except `worldgen`
(nightly-only), then trigger `nightly.yml` manually
(`gh workflow run nightly.yml`) for the full sweep including `gametest` and
`worldgen`.

All of the above must be green, or every failure must be a **known,
pre-existing, documented** limitation (see `TESTING.md` "Known
limitations") -- never silently ignore a new failure.

## 2. Test coverage matrix

| Feature | Static validation | Client smoke | Server smoke | GameTest | Worldgen/perf | Manual |
|---|---|---|---|---|---|---|
| Manifest/index structure, hashes, paths | `artifact` | -- | -- | -- | -- | -- |
| Compatibility matrix (Clockwork/VS/Eureka) | `fast`/`artifact` (build-time gate too) | -- | -- | `CoreLoadingTests` (re-validates live runtime versions) | -- | -- |
| Core mod IDs load | -- | implicit (client reaches world) | implicit (RCON commands succeed) | `CoreLoadingTests` | -- | main menu / mod list |
| Registry entries (blocks/items/dimensions) exist | -- | -- | command-smoke checks | `CoreLoadingTests` | -- | JEI search |
| Create block placement + block-entity ticking | -- | -- | `create:cogwheel` sentinel command | `CreateKineticTests` | -- | build a small contraption |
| Create kinetic rotation | -- | -- | -- | `CreateKineticTests` (reflection, degrades gracefully) | -- | watch a water wheel spin |
| Ad Astra dimensions registered | -- | -- | -- | `AdAstraTests` | worldgen suite can target Ad Astra dims where supported | travel to the Moon |
| VS/Eureka ship blocks place + report shape | -- | -- | `vs_eureka:anchor` sentinel command | `ValkyrienEurekaTests` | -- | assemble and fly a small ship |
| Clockwork/VS integration | -- | -- | `vs_clockwork:propeller_bearing` sentinel command | `ClockworkIntegrationTests` | -- | attach a propeller to a ship, fly it |
| Block-entity NBT persistence | -- | save/reopen (whole world) | save-all + restart (whole world) | `PersistenceTests` (single block entity, generic round-trip) | -- | disconnect/reconnect |
| Supplementaries/Amendments decoration blocks | -- | -- | `amendments:wall_lantern` sentinel command | `DecorationTests` | -- | visual inspection |
| Client startup, main menu, world creation | -- | `client` suite | -- | -- | -- | Modrinth App / Prism / PollyMC import |
| Chunk loading | -- | `client` suite (wait-for-chunks) | `server` suite (`forceload`) | -- | worldgen suite (pre-gen) | fly around after spawn |
| World save + reopen | -- | `client` suite (2nd launch) | `server` suite (restart) | -- | -- | manual save/quit/reopen |
| Dedicated server health/RCON | -- | -- | `server` suite | -- | -- | -- |
| Reproducible build | `artifact` suite (double-build + SHA-256 compare) | -- | -- | -- | -- | -- |
| Independent installer (non-project code) | `artifact` suite (minecraft-launcher-lib) | -- | -- | -- | -- | Prism/PollyMC/Modrinth App import itself |
| Performance under load | -- | -- | -- | -- | worldgen suite (TPS/health snapshot) | subjective play-session feel |
| Multiplayer with a second real player | -- | -- | -- | -- | -- | manual only |
| Shaders/rendering quality | -- | -- | -- | -- | -- | manual only, if supported |

## 3. Manual release checklist

Use the **exact built `.mrpack`** from `releases/` (not a source checkout,
not the previously-published Modrinth version).

### Modrinth App
- [ ] Create Instance / Import -> select the `.mrpack`.
- [ ] Installation completes without error.
- [ ] Launch with Java 17.

### Prism Launcher
- [ ] Add Instance -> Import -> select the `.mrpack`.
- [ ] Installation completes without error.
- [ ] Launch with Java 17.

### PollyMC 8.0
- [ ] Add Instance -> Import -> select the `.mrpack`.
- [ ] Installation completes without error.
- [ ] Launch with Java 17.

### Core experience (repeat once per launcher above, or at minimum once)
- [ ] Main menu reached, no crash/warning modal blocking world entry.
- [ ] Create a fresh singleplayer world.
- [ ] Chunks load around spawn within a reasonable time.
- [ ] Place and power a small Create contraption (e.g. a water wheel into a
      shaft into a cogwheel) -- rotation is visible.
- [ ] Assemble a small Eureka/Valkyrien Skies ship and move it a short
      distance.
- [ ] Attach a Clockwork propeller/engine to the ship and confirm no crash
      on assembly or movement.
- [ ] Visit or otherwise confirm access to an Ad Astra dimension/content
      appropriate to current progression.
- [ ] JEI opens and search returns results; Jade/UI overlays render.
- [ ] Place a Supplementaries and an Amendments decoration block near each
      other (e.g. a candle holder and a wall lantern).
- [ ] Save and quit, then reopen the same world -- placed blocks and ship
      position persisted.
- [ ] Models/textures render without obvious missing-texture (purple/black)
      blocks.
- [ ] Sound plays (ambient, block interaction).
- [ ] Shaders/advanced rendering, if the player has a shader pack enabled,
      does not crash the client (informational only -- not a supported
      configuration).
- [ ] Client exits cleanly (no hang, no crash on quit).
- [ ] If anything above failed: collect `logs/latest.log`, `logs/debug.log`,
      and any `crash-reports/*.txt` before closing the launcher.

## 4. Sign-off

- [ ] All automated suites green or failures match documented known
      limitations exactly.
- [ ] Manual checklist completed on at least one launcher.
- [ ] `CHANGELOG.md` updated.
- [ ] `releases/SHA256SUMS` matches the artifacts being published.
