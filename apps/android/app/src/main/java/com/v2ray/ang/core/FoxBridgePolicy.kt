package com.v2ray.ang.core

import com.google.gson.JsonParser
import com.google.gson.JsonObject

/** DNS stays in the tunnel, using the HTTPS ports carried by the provider. */
internal object FoxBridgePolicy {
    fun apply(json: JsonObject) {
        json.add("dns", JsonParser.parseString("""{
            "servers":["https://1.1.1.1/dns-query","https://8.8.8.8/dns-query"],
            "queryStrategy":"UseIP","tag":"fox-doh"
        }"""))
        json.getAsJsonArray("outbounds").add(JsonParser.parseString("""{
            "tag":"fox-dns","protocol":"dns","settings":{}
        }"""))
        val rules = json.getAsJsonObject("routing").getAsJsonArray("rules")
        rules.add(JsonParser.parseString("""{"type":"field","port":"53","outboundTag":"fox-dns"}"""))
        rules.add(JsonParser.parseString("""{"type":"field","inboundTag":["fox-doh"],"outboundTag":"proxy"}"""))
        // TLS on 853 cannot be rewritten to HTTPS without impersonating a DNS
        // server. Refuse it locally; Android's automatic Private DNS can fall
        // back to the VPN DNS. Strict custom Private DNS remains strict.
        rules.add(JsonParser.parseString("""{"type":"field","network":"tcp","port":"853","outboundTag":"block"}"""))
    }
}
