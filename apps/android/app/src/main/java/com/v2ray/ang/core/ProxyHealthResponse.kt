package com.v2ray.ang.core

import java.net.URI

internal object ProxyHealthResponse {
    fun targets(url: String): List<String> {
        val uri = runCatching { URI(url) }.getOrNull()
        val builtIn = uri?.host in setOf("www.google.com", "www.gstatic.com", "www.youtube.com", "www.googlevideo.com") && uri?.path?.trimEnd('/') == "/generate_204"
        return if (builtIn) listOf(url, "https://cp.cloudflare.com/generate_204", "https://detectportal.firefox.com/success.txt", "https://www.apple.com/library/test/success.html") else listOf(url)
    }
    fun accepts(url: String, status: Int, body: String): Boolean {
        if (status !in 200..299 || body.length > 65536) return false
        val uri = runCatching { URI(url) }.getOrNull() ?: return false
        if (uri.path.orEmpty().trimEnd('/').endsWith("generate_204", ignoreCase = true))
            return status == 204 && body.isEmpty()
        if (uri.host.equals("www.msftconnecttest.com", ignoreCase = true) && uri.path == "/connecttest.txt")
            return status == 200 && body.trim() == "Microsoft Connect Test"
        if (uri.host.equals("www.apple.com", ignoreCase = true) && uri.path == "/library/test/success.html")
            return status == 200 && body.contains("<TITLE>Success</TITLE>", ignoreCase = true)
        if (uri.host.equals("detectportal.firefox.com", ignoreCase = true) && uri.path == "/success.txt")
            return status == 200 && body.trim() == "success"
        return true
    }
}
