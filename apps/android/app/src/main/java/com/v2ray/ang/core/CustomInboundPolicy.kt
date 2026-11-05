package com.v2ray.ang.core

import com.google.gson.JsonObject

/** Keep a custom profile's tags/routing while using the app's actual SOCKS port. */
internal object CustomInboundPolicy {
    fun apply(config: JsonObject, port: Int, share: Boolean) {
        require(port in 1024..65535)
        var first = true
        config.getAsJsonArray("inbounds")?.forEach { entry ->
            if (!entry.isJsonObject) return@forEach
            val inbound = entry.asJsonObject
            if (inbound.get("protocol")?.asString !in listOf("socks", "mixed", "http")) return@forEach
            // A subscription must not expose an unauthenticated LAN proxy
            // when sharing is disabled. Internal DNS/TUN inbounds are retained.
            if (!share) inbound.addProperty("listen", "127.0.0.1")
            if (first) { inbound.addProperty("port", port); first = false }
        }
    }
}
