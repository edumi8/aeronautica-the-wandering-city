package com.aeronautica.gametest.tests;

import com.aeronautica.gametest.TestSupport;
import net.minecraft.core.BlockPos;
import net.minecraft.gametest.framework.GameTest;
import net.minecraft.gametest.framework.GameTestAssertException;
import net.minecraft.gametest.framework.GameTestHelper;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.shapes.VoxelShape;
import net.minecraftforge.gametest.GameTestHolder;
import net.minecraftforge.gametest.PrefixGameTestTemplate;

/**
 * Coverage target 8: a verified Valkyrien Skies / Eureka observable
 * behavior. Places two real Eureka ship-assembly blocks and exercises their
 * collision-shape code path -- a common real-world crash point for blocks
 * whose shape/behavior is conditioned on VS ship attachment state -- rather
 * than a bare registry-presence check (already covered by
 * CoreLoadingTests#testCriticalRegistryEntriesExist).
 */
@GameTestHolder(com.aeronautica.gametest.AeronauticaGameTestMod.MOD_ID)
@PrefixGameTestTemplate(false)
public final class ValkyrienEurekaTests {

    private ValkyrienEurekaTests() {}

    @GameTest(template = "empty_platform", setupTicks = 1, timeoutTicks = 100)
    public static void testEurekaShipBlocksPlaceAndReportShape(GameTestHelper helper) {
        BlockPos anchorPos = new BlockPos(1, 1, 1);
        BlockPos helmPos = new BlockPos(3, 1, 3);

        Block anchor = TestSupport.requireBlock("vs_eureka:anchor");
        Block helm = TestSupport.requireBlock("vs_eureka:oak_ship_helm");

        helper.setBlock(anchorPos, anchor.defaultBlockState());
        helper.setBlock(helmPos, helm.defaultBlockState());

        BlockState placedAnchor = helper.getBlockState(anchorPos);
        BlockState placedHelm = helper.getBlockState(helmPos);
        if (placedAnchor.getBlock() != anchor) {
            throw new GameTestAssertException("vs_eureka:anchor did not remain placed at " + anchorPos);
        }
        if (placedHelm.getBlock() != helm) {
            throw new GameTestAssertException("vs_eureka:oak_ship_helm did not remain placed at " + helmPos);
        }

        // Exercises real mod code (custom shape/behavior for ship-attachable
        // blocks); any exception here fails the test via the GameTest
        // framework's standard exception handling.
        VoxelShape anchorShape = placedAnchor.getShape(helper.getLevel(), helper.absolutePos(anchorPos));
        VoxelShape helmShape = placedHelm.getShape(helper.getLevel(), helper.absolutePos(helmPos));
        if (anchorShape == null || helmShape == null) {
            throw new GameTestAssertException("Eureka ship block returned a null collision shape");
        }
        helper.succeed();
    }
}
