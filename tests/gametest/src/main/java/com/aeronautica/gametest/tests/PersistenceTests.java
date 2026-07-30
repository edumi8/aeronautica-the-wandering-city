package com.aeronautica.gametest.tests;

import com.aeronautica.gametest.TestSupport;
import net.minecraft.core.BlockPos;
import net.minecraft.gametest.framework.GameTest;
import net.minecraft.gametest.framework.GameTestAssertException;
import net.minecraft.gametest.framework.GameTestHelper;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.entity.BlockEntity;
import net.minecraft.world.level.block.entity.BlockEntityType;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraftforge.gametest.GameTestHolder;
import net.minecraftforge.gametest.PrefixGameTestTemplate;

/**
 * Coverage target 7: persistence/serialization of a relevant block entity.
 * Generic round-trip (save -> load into a fresh instance -> re-save -> tags
 * equal) that proves the mod's NBT contract holds without needing to know
 * its internal field names.
 */
@GameTestHolder(com.aeronautica.gametest.AeronauticaGameTestMod.MOD_ID)
@PrefixGameTestTemplate(false)
public final class PersistenceTests {

    private PersistenceTests() {}

    @GameTest(template = "empty_platform", setupTicks = 1, timeoutTicks = 100)
    public static void testBlockEntityNbtRoundTrip(GameTestHelper helper) {
        BlockPos pos = new BlockPos(2, 1, 2);
        Block block = TestSupport.requireBlock("supplementaries:clock_block");
        BlockState state = block.defaultBlockState();
        helper.setBlock(pos, state);

        BlockEntity original = helper.getBlockEntity(pos);
        if (original == null) {
            throw new GameTestAssertException("supplementaries:clock_block did not create a BlockEntity when placed");
        }

        CompoundTag savedTag = original.saveWithoutMetadata();

        @SuppressWarnings("unchecked")
        BlockEntityType<BlockEntity> type = (BlockEntityType<BlockEntity>) original.getType();
        BlockEntity fresh = type.create(pos, state);
        if (fresh == null) {
            throw new GameTestAssertException("BlockEntityType.create returned null for supplementaries:clock_block");
        }
        fresh.load(savedTag);
        CompoundTag resavedTag = fresh.saveWithoutMetadata();

        if (!savedTag.equals(resavedTag)) {
            throw new GameTestAssertException(
                "NBT round-trip mismatch for supplementaries:clock_block: " + savedTag + " != " + resavedTag
            );
        }
        helper.succeed();
    }
}
