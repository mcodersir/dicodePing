package ir.dicode.ping.net

import ir.dicode.ping.data.GeoInfo
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class GeoResolver {
    private val client = OkHttpClient.Builder().connectTimeout(8, TimeUnit.SECONDS).readTimeout(10, TimeUnit.SECONDS).build()

    suspend fun resolve(ip: String): GeoInfo = coroutineScope {
        val a = async(Dispatchers.IO) { ipWho(ip) }
        val b = async(Dispatchers.IO) { ipApiCo(ip) }
        merge(a.await(), b.await())
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

    private fun get(url: String): JSONObject? = runCatching {
        client.newCall(Request.Builder().url(url).header("User-Agent", "dicodePing-Android/0.1.2").build()).execute().use {
            if (!it.isSuccessful) return null
            JSONObject(it.body?.string().orEmpty())
        }
    }.getOrNull()

    private fun merge(a: GeoInfo?, b: GeoInfo?): GeoInfo {
        if (a == null && b == null) return GeoInfo(confidence = "unknown")
        if (a == null) return b!!.copy(confidence = "single")
        if (b == null) return a.copy(confidence = "single")
        val sameCountry = a.countryCode.equals(b.countryCode, true) && a.countryCode.isNotBlank()
        val sameCity = a.city.equals(b.city, true) && a.city.isNotBlank()
        return GeoInfo(
            country = a.country.ifBlank { b.country }, countryCode = a.countryCode.ifBlank { b.countryCode },
            region = a.region.ifBlank { b.region }, city = if (sameCity) a.city else a.city.ifBlank { b.city },
            isp = a.isp.ifBlank { b.isp }, asn = a.asn.ifBlank { b.asn },
            confidence = if (sameCountry && sameCity) "high" else if (sameCountry) "medium" else "low"
        )
    }
}
