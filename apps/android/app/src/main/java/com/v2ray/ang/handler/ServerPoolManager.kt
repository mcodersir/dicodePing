package com.v2ray.ang.handler

import android.content.Context
import com.v2ray.ang.AppConfig
import com.v2ray.ang.core.CoreConfigManager
import com.v2ray.ang.core.CoreNativeManager
import com.v2ray.ang.dto.entities.SubscriptionItem
import com.v2ray.ang.service.RealPingExecutionLimiter
import kotlinx.coroutines.*
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import okhttp3.*
import java.io.IOException
import java.net.InetSocketAddress
import java.net.Proxy
import java.util.UUID
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

object ServerPoolManager {
    const val POOL_ID = "dicode-server-pool"
    const val CHANNELS_URL = "https://raw.githubusercontent.com/mcodersir/DicodeConfigChecker/refs/heads/main/channels.txt"
    private val running = AtomicBoolean(false)

    private suspend fun fetch(client: OkHttpClient, url: String): String = suspendCancellableCoroutine { continuation ->
        val call = client.newCall(Request.Builder().url(url).build())
        continuation.invokeOnCancellation { call.cancel() }
        call.enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) { if (continuation.isActive) continuation.resumeWithException(e) }
            override fun onResponse(call: Call, response: Response) {
                try {
                    val content = response.use {
                        check(it.isSuccessful) { "HTTP ${it.code}" }
                        val source = it.body.source()
                        val buffer = java.io.ByteArrayOutputStream()
                        val input = source.inputStream()
                        val chunk = ByteArray(8192)
                        while (true) {
                            val read = input.read(chunk)
                            if (read < 0) break
                            check(buffer.size() + read <= 2 * 1024 * 1024) { "Response too large" }
                            buffer.write(chunk, 0, read)
                        }
                        buffer.toString(Charsets.UTF_8.name())
                    }
                    if (continuation.isActive) continuation.resume(content)
                } catch (error: Exception) { if (continuation.isActive) continuation.resumeWithException(error) }
            }
        })
    }

    suspend fun run(context: Context, connect: suspend (String) -> Unit, report: (String) -> Unit): Int = withContext(Dispatchers.IO) {
        check(running.compareAndSet(false, true)) { "جمع‌آوری دیگری در حال اجراست." }
        val stage = "pool-stage-${UUID.randomUUID()}"
        try {
            CoreNativeManager.initCoreEnv(context)
            report("بروزرسانی و آزمون ساب پیش‌فرض…")
            val primary = MmkvManager.decodeSubscriptions().firstOrNull { it.guid == AppConfig.DICODE_PRIMARY_SUBSCRIPTION_ID }
                ?: error("ساب پیش‌فرض موجود نیست؛ صفحهٔ اصلی را باز کنید.")
            AngConfigManager.updateConfigViaSub(primary)
            currentCoroutineContext().ensureActive()
            val best = probe(context, MmkvManager.decodeServerList(primary.guid), false, report).minByOrNull { it.second }
                ?: error("ساب پیش‌فرض مسیر سالمی ندارد؛ دوباره تلاش کنید.")
            report("اتصال به بهترین سرور ساب پیش‌فرض…")
            connect(best.first)
            val client = OkHttpClient.Builder().connectTimeout(5, TimeUnit.SECONDS).callTimeout(15, TimeUnit.SECONDS)
                .proxy(Proxy(Proxy.Type.HTTP, InetSocketAddress("127.0.0.1", SettingsManager.getHttpPort())))
                .proxyAuthenticator { _, response ->
                    if (response.request.header("Proxy-Authorization") != null) null else response.request.newBuilder()
                        .header("Proxy-Authorization", Credentials.basic(SettingsManager.getSocksUsername().orEmpty(), SettingsManager.getSocksPassword().orEmpty())).build()
                }.build()
            val links = try {
                val channels = ServerPoolParser.channels(fetch(client, CHANNELS_URL))
                check(channels.isNotEmpty()) { "فهرست کانال‌ها خالی است." }
                val semaphore = Semaphore(8)
                val done = AtomicInteger(); val failed = AtomicInteger()
                coroutineScope {
                    channels.map { channel -> async {
                        semaphore.withPermit {
                            try { ServerPoolParser.extract(fetch(client, "https://t.me/s/$channel")) }
                            catch (cancelled: CancellationException) { throw cancelled }
                            catch (_: Exception) { failed.incrementAndGet(); emptyList() }
                            finally { report("کانال‌ها: ${done.incrementAndGet()}/${channels.size} · خطا: ${failed.get()}") }
                        }
                    } }.awaitAll().flatten().distinct()
                }
            } finally { client.connectionPool.evictAll(); client.dispatcher.executorService.shutdown() }
            currentCoroutineContext().ensureActive()
            // Candidates are isolated from every user subscription until validation completes.
            AngConfigManager.importBatchConfig(links.joinToString("\n"), stage, false)
            val accepted = probe(context, MmkvManager.decodeServerList(stage), true, report).sortedBy { it.second }
            currentCoroutineContext().ensureActive()
            check(accepted.isNotEmpty()) { "کانفیگ واجد شرایط پیدا نشد؛ استخر قبلی حفظ شد." }
            val profiles = accepted.associate { (guid, _) ->
                UUID.randomUUID().toString() to requireNotNull(MmkvManager.decodeServerConfig(guid)).copy(subscriptionId = POOL_ID)
            }
            MmkvManager.encodeSubscription(POOL_ID, SubscriptionItem(remarks = "استخر کانفیگ", lastUpdated = System.currentTimeMillis()))
            MmkvManager.saveServerProfiles(profiles, emptyMap(), POOL_ID, false)
            profiles.keys.zip(accepted).forEach { (guid, sample) -> MmkvManager.encodeServerTestDelayMillis(guid, sample.second) }
            AngConfigManager.sortByTestResultsForSub(POOL_ID)
            report("پایان · ${accepted.size} کانفیگ سالم در استخر ذخیره شد.")
            accepted.size
        } finally {
            try { MmkvManager.removeServerViaSubid(stage) } finally { running.set(false) }
        }
    }

    private suspend fun probe(context: Context, guids: List<String>, strict: Boolean, report: (String) -> Unit): List<Pair<String, Long>> = coroutineScope {
        val limit = Semaphore(4); val done = AtomicInteger(); val passed = AtomicInteger()
        guids.map { guid -> async {
            limit.withPermit {
                ensureActive()
                try {
                    val profile = MmkvManager.decodeServerConfig(guid) ?: return@withPermit null
                    val config = CoreConfigManager.getV2rayConfig4Speedtest(context, guid)
                    if (!config.status) return@withPermit null
                    val samples = mutableListOf<Long>()
                    repeat(if (strict) 3 else 1) {
                        ensureActive()
                        samples.add(RealPingExecutionLimiter.run(profile.configType) {
                            CoreNativeManager.measureOutboundDelay(config.content, SettingsManager.getDelayTestUrl())
                        })
                    }
                    if (if (strict) ServerPoolParser.accepts(samples) else samples[0] > 0) {
                        passed.incrementAndGet(); guid to samples.sorted()[samples.size / 2]
                    } else null
                } finally { report("آزمون واقعی ${if (strict) "سه‌مرحله‌ای" else "ساب پیش‌فرض"}: ${done.incrementAndGet()}/${guids.size} · سالم: ${passed.get()}") }
            }
        } }.awaitAll().filterNotNull()
    }
}
