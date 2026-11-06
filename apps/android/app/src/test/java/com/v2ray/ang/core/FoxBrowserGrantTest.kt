package com.v2ray.ang.core

import com.google.gson.JsonParser
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test

class FoxBrowserGrantTest {
    private fun payload() = JsonParser.parseString("""{"email":"fixture@example.test","access_token":"${"a".repeat(64)}","refresh_token":"${"b".repeat(64)}","expires_in":3600}""").asJsonObject
    @Test fun browserGrantRetainsExistingCoreStateFormat() {
        val state = FoxBrowserGrant.parse(payload().toString(), 1000)!!
        assertEquals(4600L, state.get("expires_at").asLong)
        assertEquals("a".repeat(64), state.get("access_token").asString)
        assertFalse(state.has("session_token")); assertFalse(state.has("password"))
    }
    @Test fun optionalRefreshTokenMayBeAbsent() {
        val data=payload();data.remove("refresh_token")
        val state=FoxBrowserGrant.parse(data.toString(),1000)!!
        assertFalse(state.has("refresh_token"));assertEquals(4600L,state.get("expires_at").asLong)
    }
    @Test fun rejectsMalformedGrant() {
        for ((field, value) in listOf("access_token" to "invalid", "refresh_token" to "bad\nvalue", "expires_in" to -1, "expires_in" to 31536001, "expires_in" to "3600", "email" to "bad\n@example.test")) {
            val data=payload()
            when(value) { is Number -> data.addProperty(field, value); else -> data.addProperty(field, value.toString()) }
            assertNull(FoxBrowserGrant.parse(data.toString()))
        }
    }
}
