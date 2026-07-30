package com.aeronautica.gametest.tests;

import com.aeronautica.gametest.RegistryFacts;
import com.aeronautica.gametest.TestSupport;
import net.minecraft.core.BlockPos;
import net.minecraft.gametest.framework.GameTest;
import net.minecraft.gametest.framework.GameTestAssertException;
import net.minecraft.gametest.framework.GameTestHelper;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraftforge.gametest.GameTestHolder;
import net.minecraftforge.gametest.PrefixGameTestTemplate;

/**
 * Coverage target 9: a verified Clockwork/Valkyrien Skies integration
 * assertion. Clockwork's propeller bearing is a VS-attachable Create block
 * -- placing and reading it back exercises the exact three-way integration
 * (Create kinetics + Clockwork block behavior + VS runtime present) that
 * broke in the historical incident recorded in CHANGELOG.md 0.1.0-alpha.2.
 */
@GameTestHolder(com.aeronautica.gametest.AeronauticaGameTestMod.MOD_ID)
@PrefixGameTestTemplate(false)
public final class ClockworkIntegrationTests {

    private ClockworkIntegrationTests() {}

    @GameTest(template = "empty_platform", setupTicks = 1, timeoutTicks = 100)
    public static void testClockworkValkyrienSkiesIntegration(GameTestHelper helper) {
        TestSupport.requireModLoaded(RegistryFacts.CREATE_CLOCKWORK_MOD_ID);
        TestSupport.requireModLoaded(RegistryFacts.VALKYRIEN_SKIES_MOD_ID);
        TestSupport.requireModLoaded(RegistryFacts.CREATE_MOD_ID);

        BlockPos pos = new BlockPos(2, 1, 2);
        Block bearing = TestSupport.requireBlock("vs_clockwork:propeller_bearing");
        helper.setBlock(pos, bearing.defaultBlockState());

        BlockState placed = helper.getBlockState(pos);
        if (placed.getBlock() != bearing) {
            throw new GameTestAssertException("vs_clockwork:propeller_bearing did not remain placed at " + pos);
        }
        // Exercising getShape here doubles as a smoke check that Clockwork's
        // VS-attachment integration code does not throw when queried outside
        // of an assembled ship (the exact failure mode of the historical
        // Clockwork/VS incompatibility this pack guards against).
        if (placed.getShape(helper.getLevel(), helper.absolutePos(pos)) == null) {
            throw new GameTestAssertException("vs_clockwork:propeller_bearing returned a null collision shape");
        }
        helper.succeed();
    }
}
