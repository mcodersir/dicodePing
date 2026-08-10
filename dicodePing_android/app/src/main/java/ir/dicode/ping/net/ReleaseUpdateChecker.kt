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
            val currentVersion = version(current) ?: return@runCatching null
            val request = Request.Builder().url(URL).header("Accept", "application/vnd.github+json").build()
            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) return@use null
                val releases = JSONArray(response.body?.string().orEmpty())
                (0 until releases.length()).mapNotNull { index ->
                    val item = releases.getJSONObject(index)
                    if (item.optBoolean("draft")) return@mapNotNull null
                    val tag = item.optString("tag_name")
                    val candidate = version(tag) ?: return@mapNotNull null
                    if (candidate.major != 3 || candidate <= currentVersion) return@mapNotNull null
                    val assets = item.optJSONArray("assets") ?: JSONArray()
                    val asset = (0 until assets.length()).asSequence()
                        .map { assets.getJSONObject(it) }
                        .firstOrNull { it.optString("name").endsWith("-android.apk") }
                    asset?.let { AppRelease(tag, it.optString("browser_download_url")) }
                }.maxByOrNull { version(it.tag) ?: SemVer.ZERO }
            }
        }.getOrNull()
    }

    private data class SemVer(
        val major: Int,
        val minor: Int,
        val patch: Int,
        val pre: Int?,
    ) : Comparable<SemVer> {
        override fun compareTo(other: SemVer): Int {
            compareValuesBy(this, other, SemVer::major, SemVer::minor, SemVer::patch).let {
                if (it != 0) return it
            }
            return when {
                pre == null && other.pre == null -> 0
                pre == null -> 1
                other.pre == null -> -1
                else -> pre.compareTo(other.pre)
            }
        }
        companion object { val ZERO = SemVer(0, 0, 0, 0) }
    }

    private fun version(raw: String): SemVer? {
        val match = Regex("v?(\\d+)\\.(\\d+)\\.(\\d+)(?:-pre\\.(\\d+))?").matchEntire(raw.trim()) ?: return null
        val (major, minor, patch, pre) = match.destructured
        return SemVer(major.toInt(), minor.toInt(), patch.toInt(), pre.toIntOrNull())
    }
}
