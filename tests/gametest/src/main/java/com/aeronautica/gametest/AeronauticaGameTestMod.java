package com.aeronautica.gametest;

import net.minecraftforge.fml.common.Mod;

/**
 * Entry point for the development-only GameTest suite. All actual tests are
 * discovered automatically via {@code @GameTestHolder} on the classes under
 * {@code com.aeronautica.gametest.tests} -- nothing needs to be registered
 * here. See TESTING.md "How to add a GameTest".
 */
@Mod(AeronauticaGameTestMod.MOD_ID)
public class AeronauticaGameTestMod {
    public static final String MOD_ID = "aeronauticagametest";
}
