package com.v2ray.ang.core

import com.google.gson.JsonParser
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test

class CustomInboundPolicyTest {
    @Test fun serverlessUsesActualPortAndKeepsTagsAndRules() {
        val root = JsonParser.parseString("""{"inbounds":[{"tag":"mixed-in","protocol":"mixed","listen":"0.0.0.0","port":10808},{"protocol":"socks","listen":"::","port":10900}],"routing":{"rules":[{"inboundTag":["mixed-in"]}]}}""").asJsonObject
        val rules = root["routing"].deepCopy()
        CustomInboundPolicy.apply(root, 28123, false)
        assertEquals(28123, root.getAsJsonArray("inbounds")[0].asJsonObject["port"].asInt)
        assertEquals("mixed-in", root.getAsJsonArray("inbounds")[0].asJsonObject["tag"].asString)
        root.getAsJsonArray("inbounds").forEach { assertEquals("127.0.0.1", it.asJsonObject["listen"].asString) }
        assertEquals(rules, root["routing"])
    }
    @Test fun explicitSharingKeepsCustomBinding() {
        val root = JsonParser.parseString("""{"inbounds":[{"protocol":"mixed","listen":"0.0.0.0","port":10808}]}""").asJsonObject
        CustomInboundPolicy.apply(root, 10808, true)
        assertEquals("0.0.0.0", root.getAsJsonArray("inbounds")[0].asJsonObject["listen"].asString)
    }
}
