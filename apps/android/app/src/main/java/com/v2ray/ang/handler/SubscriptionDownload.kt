package com.v2ray.ang.handler

import com.v2ray.ang.dto.UrlContentRequest
import com.v2ray.ang.util.HttpUtil
import java.io.IOException
import java.net.InetSocketAddress
import java.net.Socket

/** Download once per available route, preserving the caller's headers and timeout. */
internal object SubscriptionDownload {
    // Subscription workers can run in another process, where the core's
    // in-memory running flag is unavailable. Check the actual loopback listener.
    fun isProxyListening(port: Int): Boolean {
        if (port !in 1..65535) return false
        return try {
            Socket().use { it.connect(InetSocketAddress("127.0.0.1", port), 300) }
            true
        } catch (_: IOException) { false }
    }

    fun fetch(
        request: UrlContentRequest,
        proxyRunning: Boolean,
        directFirst: Boolean = false,
        accept: (String) -> Boolean = { it.isNotBlank() },
        download: (UrlContentRequest) -> HttpUtil.UrlContentResponse = HttpUtil::getUrlContentResponseWithUserAgent
    ): HttpUtil.UrlContentResponse {
        val ports = if (proxyRunning && request.httpPort in 1..65535) {
            if (directFirst) listOf(0, request.httpPort) else listOf(request.httpPort, 0)
        } else listOf(0)
        var failure: IOException? = null
        for (port in ports) {
            if (Thread.currentThread().isInterrupted) throw InterruptedException("Subscription download interrupted")
            try {
                val response = download(request.copy(
                    httpPort = port,
                    proxyUsername = if (port == 0) null else request.proxyUsername,
                    proxyPassword = if (port == 0) null else request.proxyPassword
                ))
                if (accept(response.content)) return response
                failure = IOException("Subscription returned no usable content")
            } catch (error: IOException) {
                if (Thread.currentThread().isInterrupted) throw InterruptedException("Subscription download interrupted")
                failure = error
            }
        }
        throw failure ?: IOException("Subscription download failed")
    }
}
