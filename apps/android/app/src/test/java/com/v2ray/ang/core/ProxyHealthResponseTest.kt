package com.v2ray.ang.core

import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test

class ProxyHealthResponseTest {
    @Test fun aPortalOrRedirectCannotBecomeAGenerate204Ping() {
        val url = "https://www.google.com/generate_204"
        assertTrue(ProxyHealthResponse.accepts(url, 204, ""))
        for (status in listOf(200, 301, 302, 403, 407, 500))
            assertFalse(ProxyHealthResponse.accepts(url, status, "Sign in to network"))
        assertFalse(ProxyHealthResponse.accepts(url, 204, "unexpected body"))
    }
    @Test fun knownConnectivityPagesMustCarryTheirExpectedContent() {
        val url = "http://www.msftconnecttest.com/connecttest.txt"
        assertTrue(ProxyHealthResponse.accepts(url, 200, "Microsoft Connect Test\n"))
        assertFalse(ProxyHealthResponse.accepts(url, 200, "network login"))
        assertFalse(ProxyHealthResponse.accepts("https://test.invalid/", 200, "x".repeat(65537)))
    }
}
