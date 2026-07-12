package ir.dicode.ping.xray

import ir.dicode.ping.net.ConfigParser
import org.json.JSONArray
import org.json.JSONObject

object XrayConfigBuilder {
    fun build(raw: String, bypassDomains: String = ""): String {
        val node = ConfigParser.parse(raw) ?: error("Unsupported or invalid configuration")
        val proxyOutbound = JSONObject(node.outbound.toString()).put("tag", "proxy")
        tuneProxySocket(proxyOutbound)
        val routingRules = JSONArray()

        val domains = bypassDomains
            .lineSequence()
            .flatMap { it.split(',', ' ', ';').asSequence() }
            .map { it.trim().removePrefix("https://").removePrefix("http://").substringBefore('/') }
            .filter { it.isNotBlank() && it.length <= 253 }
            .distinct()
            .take(200)
            .toList()
        if (domains.isNotEmpty()) {
            routingRules.put(
                JSONObject()
                    .put("type", "field")
                    .put("domain", JSONArray(domains.map { "domain:$it" }))
                    .put("outboundTag", "direct")
            )
        }

        routingRules.put(
            JSONObject()
                .put("type", "field")
                .put(
                    "ip",
                    JSONArray(
                        listOf(
                            "10.0.0.0/8",
                            "172.16.0.0/12",
                            "192.168.0.0/16",
                            "127.0.0.0/8",
                            "169.254.0.0/16",
                            "::1/128",
                            "fc00::/7",
                            "fe80::/10",
                        )
                    )
                )
                .put("outboundTag", "direct")
        )

        return JSONObject().apply {
            put("log", JSONObject().put("loglevel", "warning"))
            put("stats", JSONObject())
            put(
                "policy",
                JSONObject()
                    .put(
                        "levels",
                        JSONObject().put(
                            "8",
                            JSONObject()
                                .put("handshake", 8)
                                .put("connIdle", 300)
                                .put("uplinkOnly", 2)
                                .put("downlinkOnly", 2)
                        )
                    )
                    .put(
                        "system",
                        JSONObject()
                            .put("statsOutboundUplink", true)
                            .put("statsOutboundDownlink", true)
                    )
            )
            put(
                "inbounds",
                JSONArray().put(
                    JSONObject()
                        .put("tag", "tun-in")
                        .put("protocol", "tun")
                        .put(
                            "settings",
                            JSONObject()
                                .put("name", "dicodePing0")
                                .put("mtu", 1400)
                                .put("userLevel", 8)
                        )
                        .put(
                            "sniffing",
                            JSONObject()
                                .put("enabled", true)
                                .put("destOverride", JSONArray(listOf("http", "tls", "quic")))
                        )
                )
            )
            put(
                "outbounds",
                JSONArray()
                    .put(proxyOutbound)
                    .put(JSONObject().put("tag", "direct").put("protocol", "freedom").put("settings", JSONObject()))
                    .put(JSONObject().put("tag", "block").put("protocol", "blackhole").put("settings", JSONObject()))
            )
            put(
                "routing",
                JSONObject()
                    .put("domainStrategy", "IPIfNonMatch")
                    .put("rules", routingRules)
            )
            put(
                "dns",
                JSONObject()
                    .put("servers", JSONArray(listOf("1.1.1.1", "8.8.8.8")))
                    .put("queryStrategy", "UseIP")
            )
        }.toString()
    }

    private fun tuneProxySocket(outbound: JSONObject) {
        val stream = outbound.optJSONObject("streamSettings") ?: JSONObject().also {
            outbound.put("streamSettings", it)
        }
        val sockopt = stream.optJSONObject("sockopt") ?: JSONObject().also {
            stream.put("sockopt", it)
        }
        if (!sockopt.has("domainStrategy")) sockopt.put("domainStrategy", "UseIP")
        if (!sockopt.has("happyEyeballs")) {
            sockopt.put(
                "happyEyeballs",
                JSONObject()
                    .put("tryDelayMs", 250)
                    .put("prioritizeIPv6", false)
                    .put("interleave", 1)
                    .put("maxConcurrentTry", 4)
            )
        }
        if (!sockopt.has("tcpKeepAliveIdle")) sockopt.put("tcpKeepAliveIdle", 45)
        if (!sockopt.has("tcpKeepAliveInterval")) sockopt.put("tcpKeepAliveInterval", 15)
        if (!sockopt.has("tcpUserTimeout")) sockopt.put("tcpUserTimeout", 15_000)
    }
}
