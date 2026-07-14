package ir.dicode.ping.net

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import java.util.concurrent.TimeUnit

data class AppRelease(val tag: String, val assetUrl: String)

object ReleaseUpdateChecker {
    private val client = OkHttpClient.Builder().callTimeout(5, TimeUnit.SECONDS).build()
    private const val URL = "https://api.github.com/repos/mcodersir/dicodePing/releases"

    suspend fun newerThan(current: String): AppRelease? = withContext(Dispatchers.IO) {
        runCatching {
            val request = Request.Builder().url(URL).header("Accept", "application/vnd.github+json").build()
            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) return@use null
                val releases = JSONArray(response.body?.string().orEmpty())
                (0 until releases.length()).mapNotNull { index ->
                    val item = releases.getJSONObject(index)
                    val tag = item.optString("tag_name")
                    if (compare(version(tag), version(current)) <= 0) null else {
                        val assets = item.optJSONArray("assets") ?: JSONArray()
                        val asset = (0 until assets.length()).map { assets.getJSONObject(it) }
                            .firstOrNull { it.optString("name").contains("-android.apk") }
                        asset?.let { AppRelease(tag, it.optString("browser_download_url")) }
                    }
                }.maxWithOrNull { left, right -> compare(version(left.tag), version(right.tag)) }
            }
        }.getOrNull()
    }

    private fun version(raw: String): List<Int> {
        val match = Regex("v?(\\d+)\\.(\\d+)\\.(\\d+)(?:-rc\\.(\\d+))?").matchEntire(raw) ?: return listOf(0,0,0,0,0)
        val (major, minor, patch, rc) = match.destructured
        return listOf(major.toInt(), minor.toInt(), patch.toInt(), if (rc.isBlank()) 1 else 0, rc.toIntOrNull() ?: 0)
    }

    private fun compare(left: List<Int>, right: List<Int>): Int {
        for (index in left.indices) {
            val result = left[index].compareTo(right[index])
            if (result != 0) return result
        }
        return 0
    }
}
