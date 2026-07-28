package ir.dicode.ping.core

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ExternalCoreCommandBuilderTest {
    @Test
    fun aetherUsesMasqueAndAddsHttp2FallbackOnlyOnRetry() {
        val primary = ExternalCoreCommandBuilder.runtime(
            coreId = "aether",
            binary = "/native/libaether.so",
            config = "/state/config.json",
            socksPort = 1819,
            http2Fallback = false,
        )
        val fallback = ExternalCoreCommandBuilder.runtime(
            coreId = "aether",
            binary = "/native/libaether.so",
            config = "/state/config.json",
            socksPort = 1819,
            http2Fallback = true,
        )

        assertTrue("--masque" in primary)
        assertTrue("--quick-reconnect" in primary)
        assertFalse("--h2" in primary)
        assertTrue("--h2" in fallback)
        assertTrue("--fragment" in fallback)
    }

    @Test
    fun warpUsesPersistentSocksAndHttp2Fallback() {
        val primary = ExternalCoreCommandBuilder.runtime(
            coreId = "warp",
            binary = "/native/libusque.so",
            config = "/state/config.json",
            socksPort = 1820,
            http2Fallback = false,
        )
        val fallback = ExternalCoreCommandBuilder.runtime(
            coreId = "warp",
            binary = "/native/libusque.so",
            config = "/state/config.json",
            socksPort = 1820,
            http2Fallback = true,
        )

        assertTrue("socks" in primary)
        assertTrue("--always-reconnect" in primary)
        assertFalse("--http2" in primary)
        assertTrue("--http2" in fallback)
    }

    @Test
    fun warpRegistrationIsNonInteractive() {
        val command = ExternalCoreCommandBuilder.registration(
            binary = "/native/libusque.so",
            config = "/state/config.json",
        )

        assertTrue("register" in command)
        assertTrue("--accept-tos" in command)
        assertTrue("--name" in command)
    }
}
