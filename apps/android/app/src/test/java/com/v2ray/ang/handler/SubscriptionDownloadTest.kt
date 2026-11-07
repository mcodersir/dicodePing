package com.v2ray.ang.handler

import com.v2ray.ang.dto.UrlContentRequest
import com.v2ray.ang.util.HttpUtil
import java.io.IOException
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test

class SubscriptionDownloadTest {
    private val request = UrlContentRequest(
        url = "https://example.test/sub", timeout = 30000, httpPort = 10809,
        proxyUsername = "proxy-user", proxyPassword = "proxy-password",
        userAgent = "CustomClient", requestHeaders = "{\"X-Feed\":\"custom\"}"
    )

    @Test fun stoppedVpnSkipsLocalProxyAndDoesNotSendItsCredentials() {
        val calls = mutableListOf<UrlContentRequest>()
        val result = SubscriptionDownload.fetch(request, false) {
            calls += it
            HttpUtil.UrlContentResponse("vless://fixture", mapOf("subscription-userinfo" to "total=100"))
        }
        assertEquals(listOf(0), calls.map { it.httpPort })
        assertNull(calls.single().proxyUsername)
        assertNull(calls.single().proxyPassword)
        assertEquals("total=100", result.headers["subscription-userinfo"])
    }

    @Test fun failedProxyFallsBackOnceWithSameTimeoutAndCustomHeaders() {
        val calls = mutableListOf<UrlContentRequest>()
        SubscriptionDownload.fetch(request, true) {
            calls += it
            if (it.httpPort != 0) throw IOException("Connection refused")
            HttpUtil.UrlContentResponse("vless://fixture", emptyMap())
        }
        assertEquals(listOf(10809, 0), calls.map { it.httpPort })
        calls.forEach {
            assertEquals(request.timeout, it.timeout)
            assertEquals(request.userAgent, it.userAgent)
            assertEquals(request.requestHeaders, it.requestHeaders)
        }
        assertEquals("proxy-password", calls.first().proxyPassword)
    }

    @Test fun primaryFeedCanRetryWithAuthenticatedProxy() {
        val calls = mutableListOf<Int>()
        SubscriptionDownload.fetch(request, true, directFirst = true) {
            calls += it.httpPort
            if (it.httpPort == 0) throw IOException("Direct route blocked")
            assertEquals(request.proxyUsername, it.proxyUsername)
            HttpUtil.UrlContentResponse("vless://fixture", emptyMap())
        }
        assertEquals(listOf(0, 10809), calls)
    }

    @Test fun failedDownloadNeverReturnsAnEmptySuccessfulResponse() {
        assertThrows(IOException::class.java) {
            SubscriptionDownload.fetch(request, false) { HttpUtil.UrlContentResponse(" ", emptyMap()) }
        }
    }

    @Test fun primaryFeedRetriesWhenDirectRouteReturnsAnHtmlBlockPage() {
        val calls = mutableListOf<Int>()
        val result = SubscriptionDownload.fetch(
            request, true, directFirst = true,
            accept = { PrimarySubscriptionSources.extractLinks(it).isNotEmpty() }
        ) {
            calls += it.httpPort
            HttpUtil.UrlContentResponse(
                if (it.httpPort == 0) "<html>Access denied</html>" else "vless://fixture@server.test:443",
                emptyMap()
            )
        }
        assertEquals(listOf(0, 10809), calls)
        assertTrue(result.content.startsWith("vless://"))
    }

    @Test fun interruptionDoesNotStartAnotherRoute() {
        var calls = 0
        try {
            assertThrows(InterruptedException::class.java) {
                SubscriptionDownload.fetch(request, true) {
                    calls++
                    Thread.currentThread().interrupt()
                    throw IOException("Cancelled")
                }
            }
            assertEquals(1, calls)
        } finally { Thread.interrupted() }
    }
}
