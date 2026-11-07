package com.v2ray.ang.core

import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test

class FoxBridgePolicyTest {
    @Test fun dnsIsInterceptedBeforeTheRestrictedProxyAndUsesHttps() {
        val config = SingBoxConfig.xrayBridge(34567, 10808)
        FoxBridgePolicy.apply(config)
        val dns = config.getAsJsonObject("dns")
        assertTrue(dns.getAsJsonArray("servers").all { it.asString.startsWith("https://") })
        val rules = config.getAsJsonObject("routing").getAsJsonArray("rules")
        assertEquals("fox-dns", rules[0].asJsonObject.get("outboundTag").asString)
        assertEquals("53", rules[0].asJsonObject.get("port").asString)
        assertEquals("proxy", rules[1].asJsonObject.get("outboundTag").asString)
        assertEquals("853", rules[2].asJsonObject.get("port").asString)
        assertEquals("block", rules[2].asJsonObject.get("outboundTag").asString)
        assertEquals(34567, config.getAsJsonArray("outbounds")[0].asJsonObject.getAsJsonObject("settings").getAsJsonArray("servers")[0].asJsonObject.get("port").asInt)
    }
}
