package com.aeronautica.gametest.tests;

import com.aeronautica.gametest.RegistryFacts;
import com.aeronautica.gametest.TestSupport;
import net.minecraft.core.BlockPos;
import net.minecraft.gametest.framework.GameTest;
import net.minecraft.gametest.framework.GameTestAssertException;
import net.minecraft.gametest.framework.GameTestHelper;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.entity.BlockEntity;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraftforge.gametest.GameTestHolder;
import net.minecraftforge.gametest.PrefixGameTestTemplate;

/**
 * Coverage target 10: Supplementaries/Amendments presence and a relevant
 * block behavior. Amendments restores several decoration blocks that
 * Supplementaries moved out (see CHANGELOG.md 0.1.0-alpha.3) -- this test
 * places one from each mod and confirms both survive placement + shape
 * queries, which is exactly the kind of cross-mod decoration interaction
 * that motivated adding Amendments to the pack.
 */
@GameTestHolder(com.aeronautica.gametest.AeronauticaGameTestMod.MOD_ID)
@PrefixGameTestTemplate(false)
public final class DecorationTests {

    private DecorationTests() {}

    @GameTest(template = "empty_platform", setupTicks = 1, timeoutTicks = 100)
    public static void testSupplementariesAmendmentsDecorationBlocks(GameTestHelper helper) {
        TestSupport.requireModLoaded(RegistryFacts.SUPPLEMENTARIES_MOD_ID);
        TestSupport.requireModLoaded(RegistryFacts.AMENDMENTS_MOD_ID);

        BlockPos clockPos = new BlockPos(1, 1, 1);
        BlockPos lanternPos = new BlockPos(3, 1, 3);

        Block clock = TestSupport.requireBlock("supplementaries:clock_block");
        Block lantern = TestSupport.requireBlock("amendments:wall_lantern");

        helper.setBlock(clockPos, clock.defaultBlockState());
        helper.setBlock(lanternPos, lantern.defaultBlockState());

        BlockState placedClock = helper.getBlockState(clockPos);
        BlockState placedLantern = helper.getBlockState(lanternPos);
        if (placedClock.getBlock() != clock) {
            throw new GameTestAssertException("supplementaries:clock_block did not remain placed at " + clockPos);
        }
        if (placedLantern.getBlock() != lantern) {
            throw new GameTestAssertException("amendments:wall_lantern did not remain placed at " + lanternPos);
        }

        BlockEntity clockEntity = helper.getBlockEntity(clockPos);
        if (clockEntity == null) {
            throw new GameTestAssertException("supplementaries:clock_block did not create a BlockEntity");
        }

        if (placedClock.getShape(helper.getLevel(), helper.absolutePos(clockPos)) == null
            || placedLantern.getShape(helper.getLevel(), helper.absolutePos(lanternPos)) == null) {
            throw new GameTestAssertException("Decoration block returned a null collision shape");
        }
        helper.succeed();
    }
}
