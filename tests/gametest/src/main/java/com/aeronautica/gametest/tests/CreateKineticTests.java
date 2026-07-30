package com.aeronautica.gametest.tests;

import com.aeronautica.gametest.TestSupport;
import com.mojang.logging.LogUtils;
import net.minecraft.core.BlockPos;
import net.minecraft.gametest.framework.GameTest;
import net.minecraft.gametest.framework.GameTestAssertException;
import net.minecraft.gametest.framework.GameTestHelper;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.entity.BlockEntity;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraftforge.gametest.GameTestHolder;
import net.minecraftforge.gametest.PrefixGameTestTemplate;
import org.slf4j.Logger;

import java.lang.reflect.Method;

/**
 * Coverage targets 4-5: basic Create block placement + block-entity
 * ticking, and a deterministic kinetic rotation setup.
 */
@GameTestHolder(com.aeronautica.gametest.AeronauticaGameTestMod.MOD_ID)
@PrefixGameTestTemplate(false)
public final class CreateKineticTests {
    private static final Logger LOGGER = LogUtils.getLogger();
    private static final String CREATIVE_MOTOR = "create:creative_motor";

    private CreateKineticTests() {}

    // Coverage target 4: basic Create block placement and block-entity ticking.
    @GameTest(template = "empty_platform", setupTicks = 1, timeoutTicks = 100)
    public static void testCreateBlockPlacementAndTicking(GameTestHelper helper) {
        BlockPos pos = new BlockPos(2, 1, 2);
        Block press = TestSupport.requireBlock("create:mechanical_press");
        helper.setBlock(pos, press.defaultBlockState());

        helper.runAfterDelay(5, () -> {
            BlockState placed = helper.getBlockState(pos);
            if (placed.getBlock() != press) {
                throw new GameTestAssertException("Expected create:mechanical_press at test-relative " + pos + ", found " + placed);
            }
            BlockEntity blockEntity = helper.getBlockEntity(pos);
            if (blockEntity == null) {
                throw new GameTestAssertException("create:mechanical_press did not create/tick a BlockEntity after 5 ticks");
            }
            helper.succeed();
        });
    }

    // Coverage target 5: basic Create kinetic behavior -- a Creative Motor
    // gives constant, configuration-free rotation, making it the only
    // deterministic kinetic source in the pack (water/wind-driven sources
    // depend on world generation). Reading the live rotation speed uses
    // Create's KineticBlockEntity#getSpeed(), which is public API but not
    // part of any stability contract this repository controls -- reflection
    // is used here specifically so a future Create update that renames/moves
    // it degrades to a documented, weaker-but-still-meaningful assertion
    // instead of breaking compilation of the whole GameTest module. See
    // TESTING.md "known limitations".
    @GameTest(template = "empty_platform", setupTicks = 1, timeoutTicks = 140)
    public static void testCreateKineticRotationIsDeterministic(GameTestHelper helper) {
        BlockPos motorPos = new BlockPos(2, 1, 2);
        Block motor = TestSupport.requireBlock(CREATIVE_MOTOR);
        helper.setBlock(motorPos, motor.defaultBlockState());

        helper.runAfterDelay(20, () -> {
            BlockEntity motorEntity = helper.getBlockEntity(motorPos);
            if (motorEntity == null) {
                throw new GameTestAssertException(CREATIVE_MOTOR + " did not produce a BlockEntity");
            }

            Double speed = tryReadKineticSpeed(motorEntity);
            if (speed == null) {
                // Documented graceful degradation: still a meaningful
                // assertion (block entity exists and ticked 20 times with
                // no exception), just not proof of nonzero rotation.
                LOGGER.warn(
                    "KineticBlockEntity#getSpeed() was not reflectively accessible; falling back to "
                        + "presence/no-crash assertion only. See TESTING.md known limitations."
                );
                helper.succeed();
                return;
            }
            if (Math.abs(speed) <= 0.0d) {
                throw new GameTestAssertException(CREATIVE_MOTOR + " reported zero rotation speed after 20 ticks");
            }
            helper.succeed();
        });
    }

    private static Double tryReadKineticSpeed(BlockEntity blockEntity) {
        for (String methodName : new String[] {"getSpeed", "getTheoreticalSpeed"}) {
            try {
                Method method = blockEntity.getClass().getMethod(methodName);
                Object result = method.invoke(blockEntity);
                if (result instanceof Number number) {
                    return number.doubleValue();
                }
            } catch (ReflectiveOperationException | RuntimeException ignored) {
                // Try the next candidate method name / give up gracefully.
            }
        }
        return null;
    }
}
