package ir.dicode.ping.net

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.ByteArrayOutputStream
import java.util.concurrent.TimeUnit

class SubscriptionClient {
    private val client = OkHttpClient.Builder().connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(35, TimeUnit.SECONDS).followRedirects(true).build()

    suspend fun download(url: String, progress: (Long, Long) -> Unit): String = withContext(Dispatchers.IO) {
        val request = Request.Builder().url(url).header("User-Agent", "dicodePing-Android/0.1.2").build()
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) error("HTTP ${response.code}")
            val body = response.body ?: error("Empty response")
            val total = body.contentLength()
            val input = body.byteStream(); val out = ByteArrayOutputStream(); val buffer = ByteArray(16 * 1024)
            var readTotal = 0L
            while (true) {
                val n = input.read(buffer); if (n < 0) break
                out.write(buffer, 0, n); readTotal += n; progress(readTotal, total)
            }
            out.toString(Charsets.UTF_8.name())
        }
    }
}
