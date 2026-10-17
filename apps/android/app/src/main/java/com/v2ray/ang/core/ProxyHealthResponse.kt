package com.v2ray.ang.core

import java.net.URI

internal object ProxyHealthResponse {
    fun accepts(url: String, status: Int, body: String): Boolean {
        if (status !in 200..299 || body.length > 65536) return false
        val uri = runCatching { URI(url) }.getOrNull() ?: return false
        if (uri.path.orEmpty().trimEnd('/').endsWith("generate_204", ignoreCase = true))
            return status == 204 && body.isEmpty()
        if (uri.host.equals("www.msftconnecttest.com", ignoreCase = true) && uri.path == "/connecttest.txt")
            return status == 200 && body.trim() == "Microsoft Connect Test"
        if (uri.host.equals("www.apple.com", ignoreCase = true) && uri.path == "/library/test/success.html")
            return status == 200 && body.contains("<TITLE>Success</TITLE>", ignoreCase = true)
        return true
    }
}
