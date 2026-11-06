package com.v2ray.ang.core

import org.json.JSONObject

/** A grant from the origin-bound official sign-in browser; stored by the existing encrypted vault. */
internal object FoxBrowserGrant {
    fun state(data: JSONObject, nowSeconds: Long = System.currentTimeMillis() / 1000): JSONObject? = runCatching {
        val email = data.opt("email") as? String ?: return@runCatching null
        val access = data.opt("access_token") as? String ?: return@runCatching null
        val refresh = if (data.isNull("refresh_token")) null else (data.opt("refresh_token") as? String ?: return@runCatching null)
        val ttl = data.get("expires_in") as? Number ?: return@runCatching null
        val seconds = ttl.toLong()
        val valid = Regex("^[A-Za-z0-9._~+/-]{16,2048}$")
        if (email.length > 254 || !email.contains('@') || email.any { it.isISOControl() } || !valid.matches(access)
            || (refresh != null && !valid.matches(refresh)) || seconds <= 0 || seconds > 31536000 || ttl.toDouble() != seconds.toDouble()) return@runCatching null
        JSONObject().put("email", email).put("access_token", access).put("refresh_token", refresh).put("expires_at", nowSeconds + seconds)
    }.getOrNull()
}
