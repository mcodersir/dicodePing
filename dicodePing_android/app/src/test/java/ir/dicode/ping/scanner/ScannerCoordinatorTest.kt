package ir.dicode.ping.scanner

import ir.dicode.ping.net.TelegramChannelCrawler
import ir.dicode.ping.net.ConfigProfileClassifier
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ScannerCoordinatorTest {
    @Test
    fun invalidRankLimitsFallBackToThree() {
        assertEquals(3, ScannerCoordinator.normalizeLimit(0))
        assertEquals(3, ScannerCoordinator.normalizeLimit(21))
        assertEquals(1, ScannerCoordinator.normalizeLimit(1))
        assertEquals(20, ScannerCoordinator.normalizeLimit(20))
    }

    @Test
    fun crawlerRejectsTelegramProxyAndKeepsSupportedSchemes() {
        val configs = TelegramChannelCrawler.extractConfigs(
            """
            tg://proxy?server=192.0.2.1
            tg://socks?server=192.0.2.2
            hysteria2://secret@example.test:443
            vless://00000000-0000-0000-0000-000000000000@example.test:443
            """.trimIndent()
        )
        assertEquals(2, configs.size)
        assertTrue(configs.any { it.startsWith("vless://") })
        assertTrue(configs.any { it.startsWith("hysteria2://") })
        assertFalse(configs.any { it.startsWith("tg://") })
    }

    @Test
    fun configProfileLabelsNeverInventUnknownLifetime() {
        assertEquals(
            ConfigProfileClassifier.Tag.WORKER,
            ConfigProfileClassifier.classify("vless://id@demo.workers.dev:443"),
        )
        assertEquals(
            ConfigProfileClassifier.Tag.LIMITED,
            ConfigProfileClassifier.classify("vless://id@example.test:443#10GB"),
        )
        assertEquals(
            ConfigProfileClassifier.Tag.UNKNOWN,
            ConfigProfileClassifier.classify("vless://id@example.test:443"),
        )
    }
}
