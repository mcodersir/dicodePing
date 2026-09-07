package com.v2ray.ang.handler

import kotlinx.coroutines.*
import java.io.IOException
import java.net.InetSocketAddress
import java.net.Socket

data class PoolProgress(val stage: String, val message: String, val completed: Int = 0,
    val total: Int = 0, val passed: Int = 0, val failed: Int = 0)

object PoolNetwork {
    suspend fun waitForListener(port: () -> Int) = withContext(Dispatchers.IO) {
        repeat(60) {
            ensureActive()
            try { Socket().use { it.connect(InetSocketAddress("127.0.0.1", port()), 500) }; return@withContext }
            catch (_: IOException) { }
            delay(500)
        }
        error("درگاه محلی هسته آماده نشد؛ گزارش اتصال را بررسی کنید.")
    }

    fun describe(error: Exception): String = when (error) {
        is java.net.SocketTimeoutException -> "پایان مهلت پاسخ"
        is java.net.UnknownHostException -> "خطای DNS"
        is javax.net.ssl.SSLException -> "خطای TLS"
        is java.net.ConnectException -> "درگاه پاسخ نمی‌دهد"
        is SourceHttpException -> "HTTP ${error.code}"
        else -> error.javaClass.simpleName
    }
    class SourceHttpException(val code: Int) : IOException("HTTP $code")

    suspend fun loadChannels(fetch: suspend (String) -> String, report: (PoolProgress) -> Unit): List<String> {
        val sources = listOf(ServerPoolManager.CHANNELS_URL,
            "https://github.com/mcodersir/DicodeConfigChecker/raw/refs/heads/main/channels.txt",
            "https://api.github.com/repos/mcodersir/DicodeConfigChecker/contents/channels.txt")
        for (source in sources) {
            repeat(2) { attempt ->
                currentCoroutineContext().ensureActive()
                try {
                    val channels = ServerPoolParser.channels(fetch(source))
                    check(channels.isNotEmpty()) { "فهرست نامعتبر" }
                    report(PoolProgress("کانال‌ها", "فهرست ${channels.size} کانال دریافت شد."))
                    return channels
                } catch (cancelled: CancellationException) { throw cancelled }
                catch (error: Exception) {
                    report(PoolProgress("کانال‌ها", "${java.net.URI(source).host} · تلاش ${attempt + 1}/۲: ${describe(error)}"))
                    if (attempt == 0) delay(750)
                }
            }
        }
        error("درگاه اتصال آماده است، اما دریافت فهرست کانال‌ها از گیت‌هاب ناموفق بود. دوباره تلاش کنید؛ این خطا به‌معنی قطع VPN نیست.")
    }
}
