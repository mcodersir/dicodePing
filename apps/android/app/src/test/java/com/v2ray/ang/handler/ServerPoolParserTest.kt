package com.v2ray.ang.handler

import java.time.Instant
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
    @Test fun channelsRejectForeignHostsAndDeduplicate() {
        assertEquals(listOf("valid_channel"), ServerPoolParser.channels("@valid_channel\nhttps://t.me/valid_channel\nt.me/valid_channel\nhttps://evil.example/x\n../foo\n#comment"))
    }
    @Test fun onlyFourRecentV2rayLinksAreCollected() {
        val old = "<div class=\"tgme_widget_message_wrap\"><time datetime=\"2026-01-01T10:00:00Z\"></time>vless://old</div>"
        val recent = "<div class=\"tgme_widget_message_wrap\"><time datetime=\"2026-09-07T10:00:00Z\"></time>tg://proxy?server=x https://t.me/proxy?server=x " +
            (1..6).joinToString(" ") { "vless://id$it@example.com:443?security=tls&amp;type=ws" } + "</div>"
        val links = ServerPoolParser.extract(old + recent, Instant.parse("2026-09-07T12:00:00Z"))
        assertEquals(4, links.size)
        assertTrue(links.all { it.startsWith("vless://id") && it.contains("&type=ws") })
    }
}
