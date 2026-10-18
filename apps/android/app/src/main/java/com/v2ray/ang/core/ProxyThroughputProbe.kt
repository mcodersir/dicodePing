package com.v2ray.ang.core

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.net.InetSocketAddress
import java.net.Proxy
import java.util.concurrent.TimeUnit

internal object ProxyThroughputProbe {
    data class Result(val downloadMbps: Double?, val uploadMbps: Double?)

    suspend fun measure(port: Int, username: String? = null, password: String? = null, downloadUrl: String = "https://speed.cloudflare.com/__down?bytes=5000000", uploadUrl: String = "https://speed.cloudflare.com/__up"): Result = coroutineScope {
        val calls = AetherDelayTester.ProbeCalls()
        val work = async(Dispatchers.IO) {
            val authenticated = !username.isNullOrBlank() && !password.isNullOrBlank()
            val client = OkHttpClient.Builder()
                .proxy(Proxy(if (authenticated) Proxy.Type.HTTP else Proxy.Type.SOCKS, InetSocketAddress("127.0.0.1", port)))
                .proxyAuthenticator { _, response ->
                    if (!authenticated || response.request.header("Proxy-Authorization") != null) null
                    else response.request.newBuilder().header("Proxy-Authorization", okhttp3.Credentials.basic(username!!, password!!)).build()
                }
                .followRedirects(false).followSslRedirects(false)
                .callTimeout(10, TimeUnit.SECONDS).build()
            try {
                val download = sample(client, calls, downloadUrl, null)
                val payload = ByteArray(1_000_000).also { java.security.SecureRandom().nextBytes(it) }
                val upload = sample(client, calls, uploadUrl, payload)
                Result(download, upload)
            } finally {
                client.connectionPool.evictAll()
                client.dispatcher.executorService.shutdown()
            }
        }
        try { work.await() } catch (e: CancellationException) { calls.cancel(); throw e }
    }

    private fun sample(client: OkHttpClient, calls: AetherDelayTester.ProbeCalls, url: String, payload: ByteArray?): Double? {
        val request = Request.Builder().url(url).header("Cache-Control", "no-cache, no-store")
            .header("Accept-Encoding", "identity").apply {
                if (payload != null) post(payload.toRequestBody("application/octet-stream".toMediaType()))
            }.build()
        return try {
            val started = System.nanoTime()
            calls.start(client.newCall(request)).execute().use { response ->
                if (!response.isSuccessful || response.header("Content-Type").orEmpty().contains("text/html")) return null
                var bytes = 0L
                response.body.byteStream().use { stream ->
                    val buffer = ByteArray(65536)
                    while (true) { val size = stream.read(buffer); if (size < 0) break; bytes += size }
                }
                val transferred = payload?.size?.toLong() ?: bytes
                if (transferred < 65536) null else transferred * 8_000.0 / (System.nanoTime() - started).coerceAtLeast(1)
            }
        } catch (_: java.io.IOException) { null }
    }
}
