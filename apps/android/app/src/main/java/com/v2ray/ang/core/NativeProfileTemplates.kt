package com.v2ray.ang.core

import com.google.gson.JsonArray
import com.google.gson.JsonObject

/** Native sing-box schemas. Authentication and certificate checks stay enabled. */
internal object NativeProfileTemplates {
    val kinds = listOf("snell", "anytls", "ssh", "openconnect", "openvpn-client", "socks")
    fun build(kind: String, server: String, port: Int, username: String, password: String, extra: String, name: String): String {
        require(kind in kinds && server.isNotBlank() && port in 1..65535) { "Server and valid port are required" }
        require(kind in listOf("ssh", "socks") || password.isNotBlank()) { "Password / PSK is required" }
        val proxy = JsonObject().apply {
            addProperty("type", kind); addProperty("tag", "proxy"); addProperty("server", server.trim()); addProperty("server_port", port)
        }
        fun strings(value: String) = JsonArray().apply { add(value) }
        when (kind) {
            "socks" -> { proxy.addProperty("version", "5"); if (username.isNotBlank()) { proxy.addProperty("username", username); proxy.addProperty("password", password) } }
            "snell" -> { proxy.addProperty("version", 4); proxy.addProperty("psk", password) }
            "anytls" -> { proxy.addProperty("password", password); proxy.add("tls", JsonObject().apply {
                addProperty("enabled", true); addProperty("server_name", extra.ifBlank { server.trim() })
            }) }
            "ssh" -> {
                require(username.isNotBlank()) { "SSH username is required" }
                proxy.addProperty("user", username); proxy.addProperty("password", password)
                if (extra.isNotBlank()) proxy.add("host_key", strings(extra.trim()))
            }
            "openconnect" -> {
                proxy.remove("server_port"); proxy.addProperty("system", false); proxy.addProperty("flavor", "anyconnect")
                val host = server.trim().let { if (it.contains(':') && !it.startsWith('[')) "[$it]" else it }
                proxy.addProperty("server", "https://$host:$port"); proxy.addProperty("username", username); proxy.addProperty("password", password)
                if (extra.isNotBlank()) proxy.add("tls", JsonObject().apply { add("certificate_authority", strings(extra)) })
            }
            "openvpn-client" -> {
                require(extra.isNotBlank()) { "OpenVPN server CA certificate is required" }
                proxy.addProperty("system", false); proxy.addProperty("network", "udp"); proxy.addProperty("mode", "tls")
                proxy.addProperty("username", username); proxy.addProperty("password", password)
                proxy.add("tls", JsonObject().apply { addProperty("server_name", server.trim()); add("certificate", strings(extra)) })
            }
        }
        return JsonObject().apply {
            addProperty("remarks", name.ifBlank { kind }); add("log", JsonObject().apply { addProperty("level", "warn") })
            add("inbounds", JsonArray().apply { add(JsonObject().apply { addProperty("type", "mixed"); addProperty("tag", "socks"); addProperty("listen", "127.0.0.1"); addProperty("listen_port", 1080) }) })
            add(if (kind in listOf("openconnect", "openvpn-client")) "endpoints" else "outbounds", JsonArray().apply { add(proxy) })
            add("route", JsonObject().apply { addProperty("final", "proxy") })
        }.toString()
    }
}
