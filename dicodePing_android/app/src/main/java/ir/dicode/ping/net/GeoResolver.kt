package ir.dicode.ping.net

import ir.dicode.ping.data.GeoInfo
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.util.concurrent.TimeUnit
import java.util.concurrent.ConcurrentHashMap

class GeoResolver {
    private val client = OkHttpClient.Builder()
        .connectTimeout(4, TimeUnit.SECONDS)
        .readTimeout(5, TimeUnit.SECONDS)
        .callTimeout(7, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .build()
    private val cache = ConcurrentHashMap<String, GeoInfo>()

    suspend fun resolve(ip: String): GeoInfo = withContext(Dispatchers.IO) {
        cache[ip]?.let { return@withContext it }
        // A single successful provider is enough for the list. Calling both services for
        // every server doubled refresh time and quickly hit public API rate limits.
        val resolved = ipWho(ip)?.copy(confidence = "single")
            ?: ipApiCo(ip)?.copy(confidence = "single")
            ?: ipApiIs(ip)?.copy(confidence = "single")
            ?: GeoInfo(confidence = "unknown")
        if (resolved.countryCode.isNotBlank()) cache[ip] = resolved
        resolved
    }

    private fun ipWho(ip: String): GeoInfo? = get("https://ipwho.is/$ip")?.let { o ->
        if (!o.optBoolean("success", true)) return@let null
        val connection = o.optJSONObject("connection") ?: JSONObject()
        GeoInfo(o.optString("country"), o.optString("country_code"), o.optString("region"), o.optString("city"),
            connection.optString("isp").ifBlank { connection.optString("org") }, connection.optString("asn"))
    }

    private fun ipApiCo(ip: String): GeoInfo? = get("https://ipapi.co/$ip/json/")?.let { o ->
        if (o.has("error")) return@let null
        GeoInfo(o.optString("country_name"), o.optString("country_code"), o.optString("region"), o.optString("city"),
            o.optString("org"), o.optString("asn"))
    }

    private fun ipApiIs(ip: String): GeoInfo? = get("https://api.ipapi.is/?q=$ip")?.let { o ->
        val location = o.optJSONObject("location") ?: return@let null
        val company = o.optJSONObject("company") ?: JSONObject()
        val asn = o.optJSONObject("asn") ?: JSONObject()
        val code = location.optString("country_code")
        if (code.isBlank()) return@let null
        GeoInfo(
            location.optString("country"), code, location.optString("state"), location.optString("city"),
            company.optString("name"), asn.optString("asn"),
        )
    }

    private fun get(url: String): JSONObject? = runCatching {
        client.newCall(Request.Builder().url(url).header("User-Agent", "dicodePing-Android/0.1.5").build()).execute().use {
            if (!it.isSuccessful) return null
            JSONObject(it.body?.string().orEmpty())
        }
    }.getOrNull()

}
