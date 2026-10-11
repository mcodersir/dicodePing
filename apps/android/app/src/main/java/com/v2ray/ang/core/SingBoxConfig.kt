package com.v2ray.ang.core

import com.google.gson.JsonArray
import com.google.gson.JsonObject
import com.google.gson.JsonParser

/** Separate native engine configuration; never feed sing-box JSON to Xray. */
internal object SingBoxConfig {
    fun isConfig(raw: String): Boolean = runCatching {
        val json = JsonParser.parseString(raw).asJsonObject
        json.has("endpoints") || json.getAsJsonArray("outbounds")?.any {
            it.isJsonObject && it.asJsonObject.has("type") && !it.asJsonObject.has("protocol")
        } == true
    }.getOrDefault(false)

    fun prepare(raw: String, port: Int): String {
        require(port in 1024..65535)
        val json = JsonParser.parseString(raw).asJsonObject.deepCopy()
        require(isConfig(raw)) { "Not a sing-box configuration" }
        // Xray owns the Android VPN/TUN. Helpers use a userspace stack and a
        // loopback listener, while Android excludes this app UID from the VPN.
        val inboundTag = json.getAsJsonArray("inbounds")?.firstOrNull()?.asJsonObject?.get("tag")?.asString ?: "dicode-helper"
        json.add("inbounds", JsonArray().apply { add(JsonObject().apply {
            addProperty("type", "mixed"); addProperty("tag", inboundTag)
            addProperty("listen", "127.0.0.1"); addProperty("listen_port", port)
        }) })
        json.getAsJsonArray("endpoints")?.forEach { endpoint ->
            val e = endpoint.asJsonObject
            if (e.get("type")?.asString in listOf("openconnect", "openvpn-client")) e.addProperty("system", false)
        }
        json.remove("remarks")
        json.getAsJsonObject("log")?.remove("output")
        json.getAsJsonObject("experimental")?.remove("clash_api")
        json.getAsJsonObject("experimental")?.remove("v2ray_api")
        return json.toString()
    }

    fun xrayBridge(port: Int, listenPort: Int): JsonObject = JsonParser.parseString("""
        {"inbounds":[{"tag":"socks","listen":"127.0.0.1","port":$listenPort,"protocol":"socks","settings":{"auth":"noauth","udp":true}}],
         "outbounds":[{"tag":"proxy","protocol":"socks","settings":{"servers":[{"address":"127.0.0.1","port":$port}]}},
                      {"tag":"direct","protocol":"freedom"},{"tag":"block","protocol":"blackhole"}],
         "routing":{"domainStrategy":"AsIs","rules":[]}}
    """.trimIndent()).asJsonObject
}
