package com.aeronautica.gametest;

import net.minecraft.gametest.framework.GameTestAssertException;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.world.level.block.Block;
import net.minecraftforge.fml.ModList;
import net.minecraftforge.registries.ForgeRegistries;

/** Small shared helpers used by every test class -- kept deliberately thin. */
public final class TestSupport {
    private TestSupport() {}

    public static ResourceLocation rl(String namespacedId) {
        String[] parts = namespacedId.split(":", 2);
        if (parts.length != 2) {
            throw new GameTestAssertException("Not a namespaced id: " + namespacedId);
        }
        return new ResourceLocation(parts[0], parts[1]);
    }

    public static Block requireBlock(String namespacedId) {
        ResourceLocation id = rl(namespacedId);
        if (!ForgeRegistries.BLOCKS.containsKey(id)) {
            throw new GameTestAssertException("Block registry is missing required entry: " + namespacedId);
        }
        return ForgeRegistries.BLOCKS.getValue(id);
    }

    public static void requireItem(String namespacedId) {
        ResourceLocation id = rl(namespacedId);
        if (!ForgeRegistries.ITEMS.containsKey(id)) {
            throw new GameTestAssertException("Item registry is missing required entry: " + namespacedId);
        }
    }

    public static void requireModLoaded(String modId) {
        if (!ModList.get().isLoaded(modId)) {
            throw new GameTestAssertException("Required mod is not loaded: " + modId);
        }
    }

    public static String modVersion(String modId) {
        return ModList.get().getModContainerById(modId)
            .orElseThrow(() -> new GameTestAssertException("Mod not present in ModList: " + modId))
            .getModInfo().getVersion().toString();
    }
}
