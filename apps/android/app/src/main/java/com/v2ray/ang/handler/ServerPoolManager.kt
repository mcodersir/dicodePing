package com.v2ray.ang.handler

import android.content.Context
import com.v2ray.ang.AppConfig
import com.v2ray.ang.core.CoreNativeManager
import com.v2ray.ang.dto.entities.SubscriptionItem
import com.v2ray.ang.service.RealPingProbe
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
    const val POOL_NAME = "سرور های استخر"
    const val CHANNELS_URL = "https://raw.githubusercontent.com/mcodersir/DicodeConfigChecker/refs/heads/main/channels.txt"
    private val running = AtomicBoolean(false)

    private data class PreparedRoute(val client: OkHttpClient, val channels: List<String>, val name: String)

    fun ensureSubscription() {
        val previous = MmkvManager.decodeSubscription(POOL_ID) ?: SubscriptionItem()
        MmkvManager.encodeSubscription(POOL_ID, previous.copy(remarks = POOL_NAME, url = "", enabled = true, autoUpdate = false))
        SettingsChangeManager.makeSetupGroupTab()
    }

    private suspend fun fetch(client: OkHttpClient, url: String): String = suspendCancellableCoroutine { continuation ->
        val call = client.newCall(Request.Builder().url(url)
            .header("User-Agent", "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/128 Mobile Safari/537.36 DicodePing/4.0.0")
            .header("Accept", if (url.startsWith("https://api.github.com/")) "application/vnd.github.raw+json" else "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8")
            .header("Accept-Language", "en-US,en;q=0.8,fa;q=0.7").build())
        continuation.invokeOnCancellation { call.cancel() }
        call.enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) { if (continuation.isActive) continuation.resumeWithException(e) }
            override fun onResponse(call: Call, response: Response) {
                try {
                    val content = response.use {
                        if (!it.isSuccessful) throw PoolNetwork.SourceHttpException(it.code)
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

    private fun networkClient(proxy: Proxy?): OkHttpClient {
        val builder = OkHttpClient.Builder().connectTimeout(4, TimeUnit.SECONDS).callTimeout(8, TimeUnit.SECONDS)
        if (proxy != null) {
            builder.proxy(proxy).proxyAuthenticator { _, response ->
                if (response.request.header("Proxy-Authorization") != null) null else response.request.newBuilder()
                    .header("Proxy-Authorization", Credentials.basic(
                        SettingsManager.getSocksUsername().orEmpty(), SettingsManager.getSocksPassword().orEmpty())).build()
            }
        }
        return builder.build()
    }

    private fun localProxy() = Proxy(Proxy.Type.HTTP,
        InetSocketAddress("127.0.0.1", SettingsManager.getHttpPort()))

    private fun close(client: OkHttpClient) {
        client.connectionPool.evictAll()
        client.dispatcher.executorService.shutdown()
    }

    private suspend fun tryPrepareRoute(name: String, proxy: Proxy?, report: (PoolProgress) -> Unit): PreparedRoute? {
        val client = networkClient(proxy)
        try {
            report(PoolProgress("مسیر فعال", "بررسی $name بدون تغییر اتصال فعلی…"))
            var channels: List<String>? = null
            for (source in PoolNetwork.channelSources) {
                currentCoroutineContext().ensureActive()
                try {
                    val parsed = ServerPoolParser.channels(fetch(client, source))
                    if (parsed.isNotEmpty()) { channels = parsed; break }
                } catch (cancelled: CancellationException) { throw cancelled }
                catch (_: Exception) { }
            }
            val availableChannels = channels ?: error("Channel list unavailable")
            val telegramWorks = coroutineScope {
                availableChannels.take(5).map { channel -> async {
                    try {
                        var extraction = ServerPoolParser.inspect(fetch(client, "https://t.me/s/$channel"))
                        if (extraction.posts == 0)
                            extraction = ServerPoolParser.inspect(fetch(client, "https://telegram.me/s/$channel"))
                        extraction.posts > 0
                    } catch (cancelled: CancellationException) { throw cancelled }
                    catch (_: Exception) { false }
                } }.awaitAll().any { it }
            }
            check(telegramWorks) { "Telegram preview unavailable" }
            report(PoolProgress("مسیر فعال", "$name قابل استفاده است؛ اتصال کاربر تغییر نمی‌کند."))
            return PreparedRoute(client, availableChannels, name)
        } catch (cancelled: CancellationException) {
            close(client)
            throw cancelled
        } catch (_: Exception) {
            close(client)
            report(PoolProgress("مسیر فعال", "$name برای هر دو منبع GitHub و Telegram قابل استفاده نبود."))
            return null
        }
    }

    suspend fun run(context: Context, connect: suspend (String) -> Unit, report: (PoolProgress) -> Unit,
                    requestedOptions: ServerPoolOptions, shouldStop: () -> Boolean): Int = withContext(Dispatchers.IO) {
        check(running.compareAndSet(false, true)) { "جمع‌آوری دیگری در حال اجراست." }
        val options = requestedOptions.normalized()
        val stage = "pool-stage-${UUID.randomUUID()}"
        try {
            ensureSubscription()
            report(PoolProgress("استخر", "اشتراک مستقل «$POOL_NAME» آماده است."))
            CoreNativeManager.initCoreEnv(context)
            var route = tryPrepareRoute("اتصال فعال DicodePing", localProxy(), report)
                ?: tryPrepareRoute("مسیر مستقیم سیستم یا VPN دیگر", null, report)
            if (route == null) {
                report(PoolProgress("ساب پیش‌فرض", "مسیر فعالی برای Telegram پیدا نشد؛ آزمون ساب پیش‌فرض…"))
                val primary = MmkvManager.decodeSubscriptions().firstOrNull { it.guid == AppConfig.DICODE_PRIMARY_SUBSCRIPTION_ID }
                    ?: error("ساب پیش‌فرض موجود نیست؛ صفحهٔ اصلی را باز کنید.")
                try {
                    val update = AngConfigManager.updateConfigViaSub(primary)
                    if (update.successCount == 0)
                        report(PoolProgress("ساب پیش‌فرض", "بروزرسانی ساب نتیجه‌ای نداشت؛ cache موجود آزموده می‌شود."))
                } catch (error: Exception) {
                    report(PoolProgress("ساب پیش‌فرض", "بروزرسانی ساب در دسترس نبود (${PoolNetwork.describe(error)})؛ cache موجود آزموده می‌شود."))
                }
                currentCoroutineContext().ensureActive()
                val primaryServers = MmkvManager.decodeServerList(primary.guid)
                val best = probe(context, primaryServers, 1, primaryServers.size.coerceAtLeast(1), false, report) { false }
                    .minByOrNull { it.second }
                    ?: error("هیچ مسیر فعال یا کانفیگ سالمی در cache ساب پیش‌فرض پیدا نشد؛ دوباره تلاش کنید.")
                report(PoolProgress("اتصال", "شروع اتصال fallback به بهترین مسیر ساب پیش‌فرض · ${best.second} ms"))
                connect(best.first)
                PoolNetwork.waitForListener { SettingsManager.getHttpPort() }
                route = tryPrepareRoute("مسیر fallback ساب پیش‌فرض", localProxy(), report)
                    ?: error("اتصال fallback برقرار شد اما GitHub و Telegram از آن قابل دسترسی نیستند.")
            }
            val client = route.client
            val links = try {
                val channels = route.channels
                report(PoolProgress("کانال‌ها", "فهرست ${channels.size} کانال از ${route.name} آماده است."))
                val semaphore = Semaphore(8)
                val done = AtomicInteger(); val failed = AtomicInteger(); val found = AtomicInteger()
                coroutineScope {
                    channels.map { channel -> async {
                        semaphore.withPermit {
                            try {
                                var extraction = ServerPoolParser.inspect(fetch(client, "https://t.me/s/$channel"))
                                if (extraction.posts == 0) {
                                    extraction = ServerPoolParser.inspect(fetch(client, "https://telegram.me/s/$channel"))
                                }
                                if (extraction.posts == 0) failed.incrementAndGet()
                                found.addAndGet(extraction.links.size)
                                report(PoolProgress("جمع‌آوری", "@$channel · ${extraction.summary}"))
                                extraction.links
                            }
                            catch (cancelled: CancellationException) { throw cancelled }
                            catch (error: Exception) { failed.incrementAndGet(); report(PoolProgress("جمع‌آوری", "@$channel · ${PoolNetwork.describe(error)}")); emptyList() }
                            finally { report(PoolProgress("جمع‌آوری", "بررسی کانال‌ها", done.incrementAndGet(), channels.size, passed = found.get(), failed = failed.get())) }
                        }
                    } }.awaitAll().flatten().distinct()
                }
            } finally { close(client) }
            currentCoroutineContext().ensureActive()
            check(links.isNotEmpty()) { "از پیام‌های قابل‌دسترسی هیچ کانفیگ V2Ray استخراج نشد؛ آزمون آغاز نشد. جزئیات کانال‌ها را در لاگ بررسی کنید؛ استخر قبلی حفظ شد." }
            // Candidates are isolated from every user subscription until validation completes.
            AngConfigManager.importBatchConfig(links.joinToString("\n"), stage, false)
            val candidates = MmkvManager.decodeServerList(stage)
            check(candidates.isNotEmpty()) { "${links.size} لینک استخراج شد ولی هیچ‌کدام قابل ورود به هسته نبود؛ استخر قبلی حفظ شد." }
            report(PoolProgress("آزمون",
                "${links.size} لینک یکتا؛ ${candidates.size} کانفیگ قابل آزمون؛ هدف ${options.targetCount} سرور موفق؛ ${options.testRounds} نوبت تست واقعی همزمان",
                total = candidates.size, target = options.targetCount))
            val accepted = probe(context, candidates, options.testRounds, options.targetCount, true, report, shouldStop)
                .sortedBy { it.second }.take(options.targetCount)
            currentCoroutineContext().ensureActive()
            if (accepted.isEmpty() && shouldStop()) throw CancellationException("No completed successful result")
            check(accepted.isNotEmpty()) { "کانفیگ واجد شرایط پیدا نشد؛ استخر قبلی حفظ شد." }
            val stopped = shouldStop()
            report(PoolProgress("ذخیره", if (stopped)
                "توقف انجام شد؛ ذخیرهٔ ${accepted.size} سرور موفق تکمیل‌شده…"
                else "ذخیرهٔ ${accepted.size} کانفیگ تأییدشده…", passed = accepted.size, target = options.targetCount))
            val profiles = accepted.associate { (guid, _) ->
                UUID.randomUUID().toString() to requireNotNull(MmkvManager.decodeServerConfig(guid)).copy(subscriptionId = POOL_ID)
            }
            MmkvManager.encodeSubscription(POOL_ID, (MmkvManager.decodeSubscription(POOL_ID) ?: SubscriptionItem()).copy(
                remarks = POOL_NAME, url = "", autoUpdate = false, lastUpdated = System.currentTimeMillis()))
            MmkvManager.saveServerProfiles(profiles, emptyMap(), POOL_ID, false)
            profiles.keys.zip(accepted).forEach { (guid, sample) -> MmkvManager.encodeServerTestDelayMillis(guid, sample.second) }
            AngConfigManager.sortByTestResultsForSub(POOL_ID)
            SettingsChangeManager.makeSetupGroupTab()
            report(PoolProgress(if (stopped) "متوقف" else "پایان",
                if (stopped) "آزمایش با درخواست شما متوقف شد و ${accepted.size} سرور موفق در استخر ذخیره شد."
                else "${accepted.size} کانفیگ سالم در استخر ذخیره شد.",
                accepted.size, accepted.size, accepted.size, target = options.targetCount))
            accepted.size
        } finally {
            try { MmkvManager.removeServerViaSubid(stage) } finally { running.set(false) }
        }
    }

    private suspend fun probe(context: Context, guids: List<String>, rounds: Int, targetCount: Int,
                              strict: Boolean, report: (PoolProgress) -> Unit,
                              shouldStop: () -> Boolean): List<Pair<String, Long>> = coroutineScope {
        val limit = Semaphore(4); val done = AtomicInteger(); val passed = AtomicInteger()
        guids.mapIndexed { index, guid -> async {
            limit.withPermit {
                ensureActive()
                try {
                    if ((strict && shouldStop()) || passed.get() >= targetCount) return@withPermit null
                    if (MmkvManager.decodeServerConfig(guid) == null) return@withPermit null
                    val samples = mutableListOf<Long>()
                    repeat(rounds) {
                        ensureActive()
                        if (strict && shouldStop()) return@withPermit null
                        samples.add(try {
                            // This is exactly the same TCP-gated native probe used by
                            // the main screen's Real Ping action.
                            RealPingProbe.measure(context, guid)
                        } catch (cancelled: CancellationException) { throw cancelled }
                        catch (_: Exception) { -1L })
                        report(PoolProgress(if (strict) "آزمون" else "ساب پیش‌فرض",
                            "سرور ${index + 1} · نوبت ${it + 1}/$rounds: ${if (samples.last() > 0) "${samples.last()} ms" else "ناموفق"}",
                            passed = passed.get().coerceAtMost(targetCount), target = if (strict) targetCount else 0))
                    }
                    if (strict && shouldStop()) return@withPermit null
                    val accepted = if (strict) ServerPoolParser.accepts(samples, rounds) else samples.size == rounds && samples.all { it > 0 }
                    report(PoolProgress(if (strict) "آزمون" else "ساب پیش‌فرض",
                        "سرور ${index + 1} · ${samples.joinToString(" / ") { if (it > 0) "$it ms" else "ناموفق" }} · ${if (accepted) "پذیرفته" else "رد شد"}",
                        passed = passed.get().coerceAtMost(targetCount), target = if (strict) targetCount else 0))
                    if (accepted) {
                        val reservation = passed.incrementAndGet()
                        if (reservation <= targetCount) guid to samples.sorted()[samples.size / 2] else null
                    } else null
                } finally {
                    val completed = done.incrementAndGet()
                    val successful = passed.get().coerceAtMost(targetCount)
                    report(PoolProgress(if (strict) "آزمون" else "ساب پیش‌فرض",
                        if (strict) "آزمون واقعی مسیر · موفق $successful/$targetCount" else "آزمون واقعی مسیر",
                        completed, guids.size, successful, (completed - successful).coerceAtLeast(0), if (strict) targetCount else 0))
                }
            }
        } }.awaitAll().filterNotNull()
    }
}
