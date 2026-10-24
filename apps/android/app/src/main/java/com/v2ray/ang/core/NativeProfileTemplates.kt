package com.v2ray.ang.core

import com.google.gson.JsonArray
import com.google.gson.JsonObject

internal object NativeProfileTemplates {
    val kinds = listOf("socks")
    fun build(kind: String, server: String, port: Int, username: String, password: String, extra: String, name: String): String {
        require(kind == "socks" && server.isNotBlank() && port in 1..65535)
        return SingBoxConfig.xrayBridge(port, 1080).apply {
            addProperty("remarks", name.ifBlank { "SOCKS" })
            val remote = getAsJsonArray("outbounds")[0].asJsonObject.getAsJsonObject("settings").getAsJsonArray("servers")[0].asJsonObject
            remote.addProperty("address", server.trim())
            if (username.isNotBlank()) remote.add("users", JsonArray().apply { add(JsonObject().apply { addProperty("user", username); addProperty("pass", password) }) })
        }.toString()
    }
}
