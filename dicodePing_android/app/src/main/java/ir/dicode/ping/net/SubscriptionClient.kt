package ir.dicode.ping.net

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.ByteArrayOutputStream
import java.util.concurrent.TimeUnit

class SubscriptionClient {
    private val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(25, TimeUnit.SECONDS)
        .callTimeout(35, TimeUnit.SECONDS)
        .followRedirects(true)
        .retryOnConnectionFailure(true)
        .build()

    suspend fun download(url: String, progress: (Long, Long) -> Unit): String = withContext(Dispatchers.IO) {
        val request = Request.Builder().url(url).header("User-Agent", "dicodePing-Android/1.6").build()
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) error("HTTP ${response.code}")
            val body = response.body ?: error("Empty response")
            val total = body.contentLength()
            val input = body.byteStream(); val out = ByteArrayOutputStream(); val buffer = ByteArray(16 * 1024)
            var readTotal = 0L
            while (true) {
                val n = input.read(buffer); if (n < 0) break
                readTotal += n
                if (readTotal > MAX_SUBSCRIPTION_BYTES) error("Subscription is larger than 16 MiB")
                out.write(buffer, 0, n)
                progress(readTotal, total)
            }
            out.toString(Charsets.UTF_8.name())
        }
    }

    suspend fun revision(url: String): String = withContext(Dispatchers.IO) {
        val request = Request.Builder().url(url).head().header("User-Agent", "dicodePing-Android").build()
        runCatching {
            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) return@use ""
                listOf(response.header("ETag"), response.header("Last-Modified"), response.header("Content-Length"))
                    .joinToString("|") { it.orEmpty() }
            }
        }.getOrDefault("")
    }

    /**
     * Fetch the ``Subscription-Userinfo`` header for a subscription URL.
     *
     * Returns the raw header value (e.g.
     * ``"upload=4567; download=1234567; total=10737418240; expire=1712345678"``)
     * or ``null`` when the provider does not expose one.  This is the
     * standard v2rayN / Nekoray header for advertising the user's traffic
     * quota and is the source of the *real* remaining-volume number that
     * the user asked for in v1.6.0-rc.2.
     */
    suspend fun fetchUserinfoHeader(url: String): String? = withContext(Dispatchers.IO) {
        if (!url.startsWith("http://") && !url.startsWith("https://")) return@withContext null
        runCatching {
            val request = Request.Builder()
                .url(url)
                .head()
                .header("User-Agent", "dicodePing-Scanner/1.6")
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
