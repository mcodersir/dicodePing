package com.v2ray.ang.fmt

import com.v2ray.ang.util.Utils
import java.net.URI
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test

class LinkFragmentTest {
    @Test fun displayNamesWithBracketsEmojiAndNewlinesRemainValidUris() {
        val name = "[IR] ایران 🚀\nfast|route"
        val uri = URI(Utils.fixIllegalUrl("vless://uuid@example.com:443?type=tcp#$name"))
        assertEquals(name, uri.fragment)
        assertEquals("type=tcp", uri.rawQuery)
    }
    @Test fun existingEscapedNamesAreNotDoubleEncoded() {
        val uri = URI(Utils.fixIllegalUrl("vless://uuid@example.com:443#My%20Name"))
        assertEquals("My Name", uri.fragment)
    }
}
