package ir.dicode.ping.net

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit
import java.util.regex.Pattern

/**
 * Telegram channel crawler — Android mirror of ``dicodeping/crawler.py``.
 *
 * Mirrors the "stage 1" logic of DicodeConfigChecker: fetch
 * ``https://t.me/s/{channel}`` for each channel, extract vmess / vless /
 * trojan / ss / ssr config URIs from the preview HTML, and deduplicate.
 *
 * The scanner runs this in parallel (8 channels at a time) using the
 * program's own already-running VPN so t.me is reachable from inside
 * Iran.
 */
object TelegramChannelCrawler {
    private const val PER_CHANNEL_LIMIT = 30
    private const val MAX_WORKERS = 8
    private const val TIMEOUT_SECONDS = 12L

    private val CONFIG_PATTERNS = listOf(
        Pattern.compile("\\b(?:vmess|vless|trojan|ss|ssr|snell)://[^\\s<>\"'`\\\\]+", Pattern.CASE_INSENSITIVE),
        Pattern.compile("\\b(?:hysteria2|hy2|tuic)://[^\\s<>\"'`\\\\]+", Pattern.CASE_INSENSITIVE),
    )

    private val client: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .connectTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
            .readTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
            .followRedirects(true)
            .retryOnConnectionFailure(true)
            .build()
    }

    /** A single channel fetch result. */
    data class ChannelResult(
        val channel: String,
        val ok: Boolean,
        val configs: List<String>,
        val error: String = "",
    )

    /**
     * Crawl every channel in parallel and return a flat, deduped list of
     * unique config URIs.
     *
     * @param channels The list of channel usernames (without ``t.me/``).
     * @param progress Optional callback ``(done, total, channel)`` called
     *    after each channel completes.
     */
    suspend fun crawl(
        channels: List<String>,
        progress: ((Int, Int, String) -> Unit)? = null,
    ): List<String> = withContext(Dispatchers.IO) {
        if (channels.isEmpty()) return@withContext emptyList()
        val total = channels.size
        progress?.invoke(0, total, "")

        val seen = HashSet<String>()
        val result = mutableListOf<String>()
        val done = java.util.concurrent.atomic.AtomicInteger(0)

        // Run channels in batches of MAX_WORKERS to keep memory bounded.
        channels.chunked(MAX_WORKERS).forEach { batch ->
            coroutineScope {
                batch.map { channel ->
                    async {
                        val res = fetchChannel(channel)
                        synchronized(result) {
                            for (cfg in res.configs) {
                                val key = normalizeKey(cfg)
                                if (key in seen) continue
                                seen.add(key)
                                result.add(cfg)
                            }
                        }
                        val d = done.incrementAndGet()
                        progress?.invoke(d, total, channel)
                        res
                    }
                }.awaitAll()
            }
        }
        result
    }

    /** Fetch a single channel's preview page and extract configs. */
    suspend fun fetchChannel(channel: String): ChannelResult = withContext(Dispatchers.IO) {
        try {
            val page = fetchPreview(channel)
            val configs = extractConfigs(page).take(PER_CHANNEL_LIMIT)
            ChannelResult(channel = channel, ok = true, configs = configs)
        } catch (e: Exception) {
            ChannelResult(channel = channel, ok = false, configs = emptyList(), error = e.message ?: e.javaClass.simpleName)
        }
    }

    private fun fetchPreview(channel: String): String {
        // Try t.me first, fall back to telegram.me (mirror DicodeConfigChecker).
        val primaryUrl = "https://t.me/s/$channel"
        val request = Request.Builder()
            .url(primaryUrl)
            .header(
                "User-Agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) dicodePing-Scanner/1.6",
            )
            .header("Accept", "text/html,application/xhtml+xml,text/plain,*/*")
            .header("Accept-Language", "en-US,en;q=0.8,fa;q=0.7")
            .build()
        try {
            client.newCall(request).execute().use { response ->
                val body = response.body?.string().orEmpty()
                if (response.isSuccessful && isUsablePreview(body)) return body
            }
        } catch (_: Exception) {
            // fall through to telegram.me
        }
        val fallback = Request.Builder()
            .url("https://telegram.me/s/$channel")
            .header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) dicodePing-Scanner/1.6")
            .build()
        client.newCall(fallback).execute().use { response ->
            val body = response.body?.string().orEmpty()
            if (!response.isSuccessful || !isUsablePreview(body)) {
                throw RuntimeException("t.me and telegram.me both returned unusable preview pages")
            }
            return body
        }
    }

    private fun isUsablePreview(page: String): Boolean {
        if (page.isBlank()) return false
        val lower = page.lowercase()
        return "tgme_widget_message" in lower || "tgme_channel_info" in lower || extractConfigs(page).isNotEmpty()
    }

    /** Extract unique config URIs from a Telegram preview page. */
    fun extractConfigs(page: String): List<String> {
        if (page.isBlank()) return emptyList()
        // Decode common HTML entities inline (no Jsoup dependency).
        val text = decodeEntities(page)
        val found = mutableListOf<String>()
        val seen = HashSet<String>()
        for (pattern in CONFIG_PATTERNS) {
            val matcher = pattern.matcher(text)
            while (matcher.find()) {
                val cfg = cleanConfig(matcher.group())
                if (cfg.isBlank()) continue
                val key = normalizeKey(cfg)
                if (key in seen) continue
                seen.add(key)
                found.add(cfg)
            }
        }
        found.reverse()
        return found
    }

    private fun decodeEntities(s: String): String {
        return s
            .replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", "\"")
            .replace("&#39;", "'")
            .replace("\\u0026", "&")
    }

    private fun cleanConfig(s: String): String {
        var out = s.trim()
        // Strip trailing punctuation that Telegram's preview HTML leaves
        // attached to the URI.
        while (out.isNotEmpty() && out.last() in ")]}\"'<>،,.;") {
            out = out.dropLast(1)
        }
        return out.trim()
    }

    private fun normalizeKey(raw: String): String {
        val lower = raw.lowercase()
        return if (lower.startsWith("vmess://")) raw
        else raw.split("#", limit = 2).firstOrNull().orEmpty()
    }
}

private suspend fun <T> kotlin.collections.List<kotlinx.coroutines.Deferred<T>>.awaitAll(): List<T> =
    kotlinx.coroutines.awaitAll(*toTypedArray())
