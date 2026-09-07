package com.v2ray.ang.handler

import java.io.File
import org.junit.Assert.*
import org.junit.Test

class ServerPoolParserTest {
    @Test fun allThreeSamplesMustPass() {
        assertTrue(ServerPoolParser.accepts(listOf(1, 899, 900)))
        assertFalse(ServerPoolParser.accepts(listOf(10, -1, 20)))
        assertFalse(ServerPoolParser.accepts(listOf(10, 901, 20)))
        assertFalse(ServerPoolParser.accepts(listOf(10, 20)))
        assertFalse(ServerPoolParser.accepts(listOf(0, 20, 30)))
    }
    @Test fun userCanRequireOneOrSeveralSuccessfulRounds() {
        assertTrue(ServerPoolParser.accepts(listOf(42), 1))
        assertFalse(ServerPoolParser.accepts(listOf(-1), 1))
        assertTrue(ServerPoolParser.accepts(listOf(42, 51, 63, 70), 4))
        assertFalse(ServerPoolParser.accepts(listOf(42, 51, 901, 70), 4))
        assertFalse(ServerPoolParser.accepts(listOf(42), 0))
        assertFalse(ServerPoolParser.accepts(List(11) { 42 }, 11))
    }
    @Test fun poolOptionsAreBounded() {
        assertEquals(ServerPoolOptions(1, 1), ServerPoolOptions(-10, -2).normalized())
        assertEquals(ServerPoolOptions(200, 10), ServerPoolOptions(999, 99).normalized())
        assertEquals(ServerPoolOptions(25, 4), ServerPoolOptions(25, 4).normalized())
    }
    @Test fun channelsRejectForeignHostsAndDeduplicate() {
        assertEquals(listOf("valid_channel"), ServerPoolParser.channels("@valid_channel\nhttps://t.me/valid_channel\nt.me/valid_channel\nhttps://evil.example/x\n../foo\n#comment"))
    }
    @Test fun onlyFourRecentV2rayLinksAreCollected() {
        val old = "<div class=\"tgme_widget_message_wrap\"><time datetime=\"2026-01-01T10:00:00Z\"></time>vless://old</div>"
        val recent = "<div class=\"tgme_widget_message_wrap\"><time datetime=\"2026-09-07T10:00:00Z\"></time>tg://proxy?server=x https://t.me/proxy?server=x " +
            (1..6).joinToString(" ") { "vless://id$it@example.com:443?security=tls&amp;type=ws" } + "</div>"
        val links = ServerPoolParser.extract(old + recent)
        assertEquals(4, links.size)
        assertTrue(links.all { it.startsWith("vless://id") && it.contains("&type=ws") })
    }

    @Test fun latestAvailableLinksAreNotDiscardedAfterSevenDaysOrByDeviceClock() {
        val html = "<div class=\"tgme_widget_message_wrap js-widget_message_wrap\"><code>vless://id@example.com:443</code><time datetime=\"2026-08-30T04:42:53+00:00\">04:42</time></div>"
        val result = ServerPoolParser.inspect(html)
        assertEquals(listOf("vless://id@example.com:443"), result.links)
        assertTrue(result.summary.contains("2026-08-30"))
    }

    @Test fun attributesEntitiesAndInlineFormattingAreHandled() {
        val html = "<div data-extra='x' class = 'other tgme_widget_message_wrap js-widget_message_wrap'><time datetime = '2026-08-30T04:42:53+00:00'></time>" +
            "<code>vless://id@<span>example.com</span>:443?security=tls&#38;type=ws</code><br>tg://proxy?server=x</div>"
        assertEquals(listOf("vless://id@example.com:443?security=tls&type=ws"), ServerPoolParser.extract(html))
    }

    @Test fun unavailablePagesAndUndatedPostsHaveDifferentDiagnostics() {
        assertEquals(0, ServerPoolParser.inspect("<html>Join Telegram</html>").posts)
        val missingDate = ServerPoolParser.inspect("<div class='tgme_widget_message_wrap'>vless://id@example.com:443</div>")
        assertEquals(1, missingDate.posts)
        assertEquals(0, missingDate.datedPosts)
        assertEquals(listOf("vless://id@example.com:443"), missingDate.links)
        assertTrue(missingDate.summary.contains("تاریخ در HTML نبود"))
    }

    @Test fun wrapperlessPreviewUsesDocumentOrderAndRejectsTelegramProxy() {
        val html = "<main>vless://old@example.com:443</main><article>tg://proxy?server=x vless://new@example.com:443</article>"
        val result = ServerPoolParser.inspect(html)
        assertEquals(listOf("vless://new@example.com:443", "vless://old@example.com:443"), result.links)
        assertEquals(1, result.posts)
    }

    @Test fun releaseSmokeExtractsActualTelegramResponses() {
        val path = System.getenv("POOL_LIVE_FIXTURES")
        org.junit.Assume.assumeTrue("Live source check runs in release CI", path != null)
        val files = File(requireNotNull(path)).listFiles { file -> file.extension == "html" }!!.toList()
        assertTrue(files.isNotEmpty())
        val results = files.map { ServerPoolParser.inspect(it.readText()) }
        assertTrue("Actual Telegram responses must produce candidates", results.any { it.links.isNotEmpty() })
        results.forEach { assertTrue(it.links.size <= 4) }
    }
}
