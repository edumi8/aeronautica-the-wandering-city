package com.aeronautica.gametest.tests;

import com.aeronautica.gametest.RegistryFacts;
import net.minecraft.core.registries.Registries;
import net.minecraft.gametest.framework.GameTest;
import net.minecraft.gametest.framework.GameTestAssertException;
import net.minecraft.gametest.framework.GameTestHelper;
import net.minecraft.resources.ResourceKey;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.world.level.Level;
import net.minecraftforge.gametest.GameTestHolder;
import net.minecraftforge.gametest.PrefixGameTestTemplate;

/**
 * Coverage target 6: Ad Astra dimension/registry availability. Confirms the
 * space dimensions are actually loaded by the running server, not merely
 * declared in a datapack file that failed to parse.
 */
@GameTestHolder(com.aeronautica.gametest.AeronauticaGameTestMod.MOD_ID)
@PrefixGameTestTemplate(false)
public final class AdAstraTests {

    private AdAstraTests() {}

    @GameTest(template = "empty_platform", setupTicks = 1, timeoutTicks = 100)
    public static void testAdAstraDimensionsRegistered(GameTestHelper helper) {
        ServerLevel level = helper.getLevel();
        MinecraftServer server = level.getServer();

        for (String dimensionId : RegistryFacts.AD_ASTRA_DIMENSIONS) {
            ResourceLocation location = ResourceLocation.tryParse(dimensionId);
            if (location == null) {
                throw new GameTestAssertException("Malformed dimension id in RegistryFacts: " + dimensionId);
            }
            ResourceKey<Level> key = ResourceKey.create(Registries.DIMENSION, location);
            if (server.getLevel(key) == null) {
                throw new GameTestAssertException("Ad Astra dimension is not loaded on the running server: " + dimensionId);
            }
        }
        helper.succeed();
    }
}
