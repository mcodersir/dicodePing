package ir.dicode.ping.data

import org.json.JSONObject

data class SourceDefinition(
    val id: String,
    var name: String,
    val url: String,
    var order: Int,
    var enabled: Boolean = true,
    val isDefault: Boolean = false,
) {
    fun toJson() = JSONObject().apply {
        put("id", id); put("name", name); put("url", url); put("order", order)
        put("enabled", enabled); put("isDefault", isDefault)
    }

    companion object {
        fun fromJson(o: JSONObject) = SourceDefinition(
            o.optString("id"), o.optString("name"), o.optString("url"),
            o.optInt("order"), o.optBoolean("enabled", true), o.optBoolean("isDefault", false)
        )
    }
}

data class ServerRecord(
    val id: String,
    val raw: String,
    val name: String,
    val protocol: String,
    val host: String,
    val port: Int,
    val sourceId: String,
    val sourceName: String,
    var pingMs: Int? = null,
    var pingKind: String = "",
    var ip: String = "",
    var country: String = "",
    var countryCode: String = "",
    var region: String = "",
    var city: String = "",
    var isp: String = "",
    var asn: String = "",
    var geoConfidence: String = "",
    var healthy: Boolean = false,
    var favorite: Boolean = false,
    /** Ephemeral UI state; deliberately not persisted between app launches. */
    var testState: String = TEST_IDLE,
) {
    fun toJson() = JSONObject().apply {
        put("id", id); put("raw", raw); put("name", name); put("protocol", protocol)
        put("host", host); put("port", port); put("sourceId", sourceId); put("sourceName", sourceName)
        put("pingMs", pingMs ?: JSONObject.NULL); put("pingKind", pingKind); put("ip", ip)
        put("country", country); put("countryCode", countryCode); put("region", region); put("city", city)
        put("isp", isp); put("asn", asn); put("geoConfidence", geoConfidence)
        put("healthy", healthy); put("favorite", favorite)
    }

    companion object {
        fun fromJson(o: JSONObject) = ServerRecord(
            id=o.optString("id"), raw=o.optString("raw"), name=o.optString("name"),
            protocol=o.optString("protocol"), host=o.optString("host"), port=o.optInt("port"),
            sourceId=o.optString("sourceId", "default"), sourceName=o.optString("sourceName"),
            pingMs=if (o.isNull("pingMs")) null else o.optInt("pingMs"), pingKind=o.optString("pingKind"),
            ip=o.optString("ip"), country=o.optString("country"), countryCode=o.optString("countryCode"),
            region=o.optString("region"), city=o.optString("city"), isp=o.optString("isp"),
            asn=o.optString("asn"), geoConfidence=o.optString("geoConfidence"),
            healthy=o.optBoolean("healthy"), favorite=o.optBoolean("favorite"), testState=TEST_IDLE
        )

        const val TEST_IDLE = "idle"
        const val TEST_RUNNING = "running"
        const val TEST_FAILED = "failed"
    }
}

object ServerPolicy {
    const val MIN_AUTO_PING_MS = 70
    private val restrictedCountryNames = setOf(
        "iran", "islamic republic of iran", "ایران", "جمهوری اسلامی ایران",
    )

    fun isRestricted(server: ServerRecord): Boolean =
        server.countryCode.trim().equals("IR", ignoreCase = true) ||
            server.country.trim().lowercase() in restrictedCountryNames

    fun isAutoEligible(server: ServerRecord): Boolean =
        server.healthy &&
            server.pingKind == "PROXY_HTTP" &&
            server.pingMs != null &&
            server.pingMs!! >= MIN_AUTO_PING_MS &&
            server.countryCode.isNotBlank() &&
            !isRestricted(server)
}

data class ProgressState(
    val active: Boolean = false,
    val stage: String = "",
    val done: Int = 0,
    val total: Int = 0,
    val message: String = "",
) {
    val percent: Int get() = if (total <= 0) 0 else ((done * 100.0) / total).toInt().coerceIn(0, 100)
}

data class GeoInfo(
    val country: String = "", val countryCode: String = "", val region: String = "",
    val city: String = "", val isp: String = "", val asn: String = "", val confidence: String = ""
)


/**
 * Compatibility result used by legacy PingProbe sources that may remain when
 * upgrading the project in-place. The active server health check uses the
 * Xray outbound HTTP probe in AppRepository/CoreBridge.
 */
data class PingResult(
    val delayMs: Int?,
    val kind: String,
    val ip: String,
)

data class ParsedNode(
    val raw: String,
    val protocol: String,
    val name: String,
    val host: String,
    val port: Int,
    val outbound: JSONObject,
)
