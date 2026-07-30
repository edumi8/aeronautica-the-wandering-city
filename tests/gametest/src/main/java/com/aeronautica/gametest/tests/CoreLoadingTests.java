package com.aeronautica.gametest.tests;

import com.aeronautica.gametest.RegistryFacts;
import com.aeronautica.gametest.TestSupport;
import net.minecraft.gametest.framework.GameTest;
import net.minecraft.gametest.framework.GameTestAssertException;
import net.minecraft.gametest.framework.GameTestHelper;
import net.minecraftforge.gametest.GameTestHolder;
import net.minecraftforge.gametest.PrefixGameTestTemplate;

import java.util.List;

/**
 * Coverage targets 1-3 from TESTING.md's test-coverage matrix: core mod IDs
 * loaded, runtime versions match the tested compatibility matrix, and
 * critical registry entries exist.
 */
@GameTestHolder(com.aeronautica.gametest.AeronauticaGameTestMod.MOD_ID)
@PrefixGameTestTemplate(false)
public class CoreLoadingTests {

    private static final List<String> REQUIRED_MOD_IDS = List.of(
        RegistryFacts.CREATE_MOD_ID,
        RegistryFacts.CREATE_CLOCKWORK_MOD_ID,
        RegistryFacts.VALKYRIEN_SKIES_MOD_ID,
        RegistryFacts.EUREKA_MOD_ID,
        RegistryFacts.AD_ASTRA_MOD_ID,
        RegistryFacts.AMENDMENTS_MOD_ID,
        RegistryFacts.SUPPLEMENTARIES_MOD_ID
    );

    // Coverage target 1: core mod IDs are loaded.
    @GameTest(template = "empty_platform", setupTicks = 1, timeoutTicks = 100)
    public static void testCoreModsLoaded(GameTestHelper helper) {
        for (String modId : REQUIRED_MOD_IDS) {
            TestSupport.requireModLoaded(modId);
        }
        helper.succeed();
    }

    // Coverage target 2: runtime versions match the tested compatibility
    // matrix pinned in modpack/manifest.json (README "Tested core version
    // matrix" / scripts/aeronautica_testing/compat.py).
    @GameTest(template = "empty_platform", setupTicks = 1, timeoutTicks = 100)
    public static void testRuntimeVersionsMatchCompatibilityMatrix(GameTestHelper helper) {
        String forgeVersion = TestSupport.modVersion("forge");
        if (!forgeVersion.contains("47.4.10")) {
            throw new GameTestAssertException("Expected Forge 47.4.10 loaded, ModList reports: " + forgeVersion);
        }
        String minecraftVersion = TestSupport.modVersion("minecraft");
        if (!minecraftVersion.contains("1.20.1")) {
            throw new GameTestAssertException("Expected Minecraft 1.20.1 loaded, ModList reports: " + minecraftVersion);
        }

        // Re-validate the historical Clockwork/Valkyrien Skies rule
        // (CHANGELOG 0.1.0-alpha.2) against the versions that ACTUALLY
        // loaded together, not just what the manifest declares.
        String clockworkVersion = TestSupport.modVersion(RegistryFacts.CREATE_CLOCKWORK_MOD_ID);
        String vsVersion = TestSupport.modVersion(RegistryFacts.VALKYRIEN_SKIES_MOD_ID);
        if (!clockworkVersion.contains("0.5.6")) {
            throw new GameTestAssertException("Unexpected Clockwork runtime version: " + clockworkVersion);
        }
        if (!vsVersion.contains("2.4.11")) {
            throw new GameTestAssertException(
                "Clockwork " + clockworkVersion + " loaded against unexpected Valkyrien Skies " + vsVersion
                    + " (expected 2.4.11 per the pinned compatibility matrix)"
            );
        }
        helper.succeed();
    }

    // Coverage target 3: critical registry entries exist across the core
    // progression mods.
    @GameTest(template = "empty_platform", setupTicks = 1, timeoutTicks = 100)
    public static void testCriticalRegistryEntriesExist(GameTestHelper helper) {
        for (String blockId : RegistryFacts.CREATE_BLOCKS) {
            TestSupport.requireBlock(blockId);
        }
        for (String blockId : RegistryFacts.CREATE_CLOCKWORK_BLOCKS) {
            TestSupport.requireBlock(blockId);
        }
        for (String blockId : RegistryFacts.EUREKA_BLOCKS) {
            TestSupport.requireBlock(blockId);
        }
        for (String blockId : RegistryFacts.AD_ASTRA_BLOCKS) {
            TestSupport.requireBlock(blockId);
        }
        for (String blockId : RegistryFacts.AMENDMENTS_BLOCKS) {
            TestSupport.requireBlock(blockId);
        }
        for (String blockId : RegistryFacts.SUPPLEMENTARIES_BLOCKS) {
            TestSupport.requireBlock(blockId);
        }
        for (String itemId : RegistryFacts.VALKYRIEN_SKIES_ITEMS) {
            TestSupport.requireItem(itemId);
        }
        helper.succeed();
    }
}
