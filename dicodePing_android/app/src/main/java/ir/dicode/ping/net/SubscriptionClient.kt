package ir.dicode.ping.net

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.ByteArrayOutputStream
import java.util.concurrent.TimeUnit

/**
 * Converts a user/source supplied subscription address into a safe HTTP URL.
 *
 * User input may contain an empty value, surrounding whitespace, or a host
 * without an explicit scheme. OkHttp deliberately throws when Request.url()
 * receives such a string, so URL parsing must happen before building a request.
 */
internal fun normalizedSubscriptionHttpUrl(raw: String): HttpUrl? {
    val value = raw.trim()
    if (value.isEmpty()) return null

    val candidate = when {
        value.startsWith("http://", ignoreCase = true) -> value
        value.startsWith("https://", ignoreCase = true) -> value
        "://" in value -> return null
        else -> "https://$value"
    }

    return candidate.toHttpUrlOrNull()?.takeIf { parsed ->
        parsed.host.isNotBlank() && (parsed.scheme == "http" || parsed.scheme == "https")
    }
}

class SubscriptionClient {
    private val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(25, TimeUnit.SECONDS)
        .callTimeout(35, TimeUnit.SECONDS)
        .followRedirects(true)
        .retryOnConnectionFailure(true)
        .build()

    suspend fun download(url: String, progress: (Long, Long) -> Unit): String = withContext(Dispatchers.IO) {
        val httpUrl = requireNotNull(normalizedSubscriptionHttpUrl(url)) {
            "Subscription URL is empty or invalid. Use an http:// or https:// address."
        }
        val request = Request.Builder()
            .url(httpUrl)
            .header("User-Agent", "dicodePing-Android/3.0.0-pre.3")
            .build()

        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) error("HTTP ${response.code}")
            val body = response.body ?: error("Empty response")
            val total = body.contentLength()
            val input = body.byteStream()
            val out = ByteArrayOutputStream()
            val buffer = ByteArray(16 * 1024)
            var readTotal = 0L
            while (true) {
                val n = input.read(buffer)
                if (n < 0) break
                readTotal += n
                if (readTotal > MAX_SUBSCRIPTION_BYTES) error("Subscription is larger than 16 MiB")
                out.write(buffer, 0, n)
                progress(readTotal, total)
            }
            out.toString(Charsets.UTF_8.name())
        }
    }

    suspend fun revision(url: String): String = withContext(Dispatchers.IO) {
        val httpUrl = normalizedSubscriptionHttpUrl(url) ?: return@withContext ""
        runCatching {
            val request = Request.Builder()
                .url(httpUrl)
                .head()
                .header("User-Agent", "dicodePing-Android/3.0.0-pre.3")
                .build()
            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) return@use ""
                listOf(
                    response.header("ETag"),
                    response.header("Last-Modified"),
                    response.header("Content-Length"),
                ).joinToString("|") { it.orEmpty() }
            }
        }.getOrDefault("")
    }

    /**
     * Fetches the standard Subscription-Userinfo quota header when available.
     */
    suspend fun fetchUserinfoHeader(url: String): String? = withContext(Dispatchers.IO) {
        val httpUrl = normalizedSubscriptionHttpUrl(url) ?: return@withContext null
        runCatching {
            val request = Request.Builder()
                .url(httpUrl)
                .head()
            .header("User-Agent", "dicodePing-Scanner/3.0.0-pre.3")
                .build()
            client.newCall(request).execute().use { response ->
                response.header("Subscription-Userinfo")?.takeIf { it.isNotBlank() }
            }
        }.getOrNull()
    }

    private companion object {
        const val MAX_SUBSCRIPTION_BYTES = 16L * 1024L * 1024L
    }
}
