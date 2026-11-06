package com.v2ray.ang.core

import com.google.gson.JsonObject
import com.google.gson.JsonParser
import org.json.JSONObject

/** Origin/nonce are checked by the browser host; this validates the provider grant. */
internal object FoxBrowserGrant {
    fun state(data: JSONObject): JSONObject? = parse(data.toString())?.let { JSONObject(it.toString()) }

    // Keep validation independent of Android's JSONObject stubs so it is tested on the JVM too.
    fun parse(raw: String, nowSeconds: Long = System.currentTimeMillis() / 1000): JsonObject? = runCatching {
        if (raw.length > 8192) return@runCatching null
        val data = JsonParser.parseString(raw).asJsonObject
        fun string(name: String): String? = data.get(name)?.takeIf { it.isJsonPrimitive && it.asJsonPrimitive.isString }?.asString
        val email = string("email") ?: return@runCatching null
        val access = string("access_token") ?: return@runCatching null
        val refresh = if (!data.has("refresh_token") || data.get("refresh_token").isJsonNull) null else string("refresh_token") ?: return@runCatching null
        val ttl = data.get("expires_in")?.takeIf { it.isJsonPrimitive && it.asJsonPrimitive.isNumber } ?: return@runCatching null
        val seconds = ttl.asBigDecimal.longValueExact()
        val valid = Regex("^[A-Za-z0-9._~+/-]{16,2048}$")
        if (email.length > 254 || !email.contains('@') || email.any { it.isISOControl() } || !valid.matches(access)
            || (refresh != null && !valid.matches(refresh)) || seconds <= 0 || seconds > 31536000) return@runCatching null
        JsonObject().apply {
            addProperty("email", email); addProperty("access_token", access)
            if (refresh != null) addProperty("refresh_token", refresh)
            addProperty("expires_at", nowSeconds + seconds)
        }
    }.getOrNull()
}
