package ir.dicode.ping.net

import java.io.IOException
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.regex.Pattern
import kotlin.coroutines.coroutineContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import okhttp3.Call
import okhttp3.Callback
import okhttp3.ConnectionPool
import okhttp3.Dispatcher
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/** DicodeConfigChecker-compatible Telegram preview collector for Android. */
// Compatibility contract: repeat(2) retry budget, implemented with a breakable loop below.
object TelegramChannelCrawler {
    private const val PER_CHANNEL_LIMIT = 30
    private const val MAX_WORKERS = 4
    private const val TIMEOUT_SECONDS = 11L
    private const val MAX_PREVIEW_BYTES = 4_000_000L

    private val CONFIG_PATTERNS = listOf(
        Pattern.compile("""\b(?:vmess|vless|trojan|ss)://[^\s<>"'`\\]+""", Pattern.CASE_INSENSITIVE),
    )
    private val dispatcher = Dispatcher().apply {
        maxRequests = MAX_WORKERS
        maxRequestsPerHost = MAX_WORKERS
    }
    private val connectionPool = ConnectionPool(MAX_WORKERS, 10, TimeUnit.SECONDS)
    private val client: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .dispatcher(dispatcher)
            .connectionPool(connectionPool)
            .connectTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
            .readTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
            .writeTimeout(TIMEOUT_SECONDS, TimeUnit.SECONDS)
            .callTimeout(TIMEOUT_SECONDS + 5, TimeUnit.SECONDS)
            .followRedirects(true)
            .followSslRedirects(true)
            .retryOnConnectionFailure(true)
            .build()
    }

    data class ChannelResult(
        val channel: String,
        val ok: Boolean,
        val configs: List<String>,
        val found: Int = configs.size,
        val picked: Int = configs.size,
        val elapsedMs: Long = 0,
        val bytesReceived: Long = 0,
        val previewHost: String = "",
        val error: String = "",
    )

    suspend fun crawl(
        channels: List<String>,
        maxWorkers: Int = MAX_WORKERS,
        perChannelLimits: Map<String, Int> = emptyMap(),
        progress: ((Int, Int, String) -> Unit)? = null,
        onResult: ((ChannelResult, Int, Int) -> Unit)? = null,
        maxUniqueConfigs: Int = 180,
        minimumChannelsBeforeTarget: Int = 80,
    ): List<String> = withContext(Dispatchers.IO) {
        if (channels.isEmpty()) return@withContext emptyList()
        dispatcher.cancelAll()
        connectionPool.evictAll()
        val normalizedLimits = perChannelLimits.mapKeys { it.key.lowercase() }
        val total = channels.size
        progress?.invoke(0, total, "")
        val seen = LinkedHashSet<String>()
        val result = mutableListOf<String>()
        val done = AtomicInteger(0)
        fun limitFor(channel: String): Int = normalizedLimits[channel.lowercase()]?.coerceIn(1, 20) ?: PER_CHANNEL_LIMIT

        var preflight: ChannelResult? = null
        for (channel in channels.take(8)) {
            coroutineContext.ensureActive()
            val attempt = fetchChannel(channel, limitFor(channel))
            if (attempt.ok) { preflight = attempt; break }
            onResult?.invoke(attempt, 0, total)
        }
        val first = requireNotNull(preflight) { "Telegram preview is unreachable through the bootstrap VPN." }
        first.configs.forEach { cfg -> if (seen.add(normalizeKey(cfg))) result.add(cfg) }
        done.set(1)
        progress?.invoke(1, total, first.channel)
        onResult?.invoke(first, 1, total)

        val remaining = channels.filterNot { it.equals(first.channel, ignoreCase = true) }
        val workerCount = maxWorkers.coerceIn(1, MAX_WORKERS)
        remaining.chunked(workerCount).forEach { batch ->
            coroutineContext.ensureActive()
            coroutineScope {
                batch.map { channel -> async(Dispatchers.IO) {
                    var channelResult = ChannelResult(channel, false, emptyList(), error = "not started")
                    for (attempt in 0..1) {
                        channelResult = fetchChannel(channel, limitFor(channel))
                        if (channelResult.ok) break
                        if (attempt == 0) delay(180)
                    }
                    synchronized(result) {
                        channelResult.configs.forEach { cfg -> if (seen.add(normalizeKey(cfg))) result.add(cfg) }
                    }
                    val current = done.incrementAndGet()
                    progress?.invoke(current, total, channel)
                    onResult?.invoke(channelResult, current, total)
                }}.awaitAll()
            }
            if (done.get() >= minimumChannelsBeforeTarget && result.size >= maxUniqueConfigs) {
                return@withContext result.take(maxUniqueConfigs)
            }
        }
        result.take(maxUniqueConfigs)
    }

    suspend fun fetchChannel(channel: String, perChannelLimit: Int = PER_CHANNEL_LIMIT): ChannelResult = withContext(Dispatchers.IO) {
        val started = System.nanoTime()
        var bytes = 0L
        val errors = mutableListOf<String>()
        for ((host, url) in listOf("t.me" to "https://t.me/s/$channel", "telegram.me" to "https://telegram.me/s/$channel")) {
            coroutineContext.ensureActive()
            try {
                val payload = fetchUrl(url)
                bytes += payload.second
                if (!isUsablePreview(payload.first)) error("$host returned an unusable preview page")
                val configs = extractConfigs(payload.first)
                val picked = configs.take(perChannelLimit.coerceIn(1, 20))
                return@withContext ChannelResult(channel, true, picked, configs.size, picked.size,
                    (System.nanoTime() - started) / 1_000_000, bytes, host)
            } catch (error: Exception) {
                errors += "$host: ${error.message ?: error.javaClass.simpleName}"
            }
        }
        ChannelResult(channel, false, emptyList(), elapsedMs = (System.nanoTime() - started) / 1_000_000,
            bytesReceived = bytes, error = errors.joinToString("; ").takeLast(420))
    }

    private suspend fun fetchUrl(url: String): Pair<String, Long> = suspendCancellableCoroutine { continuation ->
        val request = Request.Builder().url(url)
            .header("User-Agent", "Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 Chrome/131 Mobile Safari/537.36")
            .header("Accept", "text/html,application/xhtml+xml,text/plain,*/*")
            .header("Accept-Language", "en-US,en;q=0.8,fa;q=0.7")
            .header("Accept-Encoding", "identity")
            .header("Connection", "close").build()
        val call = client.newCall(request)
        continuation.invokeOnCancellation { call.cancel() }
        call.enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                if (continuation.isActive) continuation.resumeWithException(e)
            }
            override fun onResponse(call: Call, response: Response) {
                response.use {
                    try {
                        if (!it.isSuccessful) error("HTTP ${it.code}")
                        val body = it.body ?: error("empty body")
                        val source = body.source()
                        source.request(MAX_PREVIEW_BYTES + 1)
                        val size = source.buffer.size
                        if (size > MAX_PREVIEW_BYTES) error("Telegram preview response is too large")
                        val value = source.buffer.clone().readUtf8(size) to size
                        if (continuation.isActive) continuation.resume(value)
                    } catch (error: Throwable) {
                        if (continuation.isActive) continuation.resumeWithException(error)
                    }
                }
            }
        })
    }

    private fun isUsablePreview(page: String): Boolean {
        if (page.isBlank()) return false
        val lower = page.lowercase()
        return "tgme_widget_message" in lower || "tgme_channel_info" in lower || extractConfigs(page).isNotEmpty()
    }

    fun extractConfigs(page: String): List<String> {
        if (page.isBlank()) return emptyList()
        val text = decodeEntities(page)
        val found = mutableListOf<String>()
        val seen = HashSet<String>()
        CONFIG_PATTERNS.forEach { pattern ->
            val matcher = pattern.matcher(text)
            while (matcher.find()) {
                val cfg = cleanConfig(matcher.group())
                if (cfg.isNotBlank() && seen.add(normalizeKey(cfg))) found.add(cfg)
            }
        }
        found.reverse()
        return found
    }

    private fun decodeEntities(value: String): String {
        var out = value.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            .replace("&quot;", "\"").replace("&#39;", "'").replace("\\u0026", "&")
        out = Regex("""&#(\d+);""").replace(out) { m -> m.groupValues[1].toIntOrNull()?.let { code -> runCatching { String(Character.toChars(code)) }.getOrNull() } ?: m.value }
        out = Regex("""&#x([0-9a-fA-F]+);""").replace(out) { m -> m.groupValues[1].toIntOrNull(16)?.let { code -> runCatching { String(Character.toChars(code)) }.getOrNull() } ?: m.value }
        return out
    }

    private fun cleanConfig(value: String): String {
        var out = value.trim().replace(Regex("""[\u200c\u200f\u202a-\u202e]"""), "")
        while (out.isNotEmpty() && out.last() in ")]\"}'<>،,.;") out = out.dropLast(1)
        return out.trim()
    }
    private fun normalizeKey(raw: String): String = if (raw.lowercase().startsWith("vmess://")) raw.trim() else raw.trim().substringBefore('#')
}
