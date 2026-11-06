package com.v2ray.ang.core

import org.json.JSONObject
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test

class FoxBrowserGrantTest {
    private fun payload() = JSONObject().put("email", "fixture@example.test").put("access_token", "a".repeat(64)).put("refresh_token", "b".repeat(64)).put("expires_in", 3600)
    @Test fun browserGrantRetainsExistingCoreStateFormat() {
        val state = FoxBrowserGrant.state(payload(), 1000)!!
        assertEquals(4600L, state.getLong("expires_at"))
        assertEquals("a".repeat(64), state.getString("access_token"))
        assertFalse(state.has("session_token")); assertFalse(state.has("password"))
    }
    @Test fun rejectsMalformedGrant() {
        for ((field, value) in listOf("access_token" to "invalid", "refresh_token" to "bad\nvalue", "expires_in" to -1, "expires_in" to 31536001, "expires_in" to "3600", "email" to "bad\n@example.test")) {
            assertNull(FoxBrowserGrant.state(payload().put(field, value)))
        }
    }
}
