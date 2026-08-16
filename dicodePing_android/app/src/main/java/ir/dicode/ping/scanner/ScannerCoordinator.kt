package ir.dicode.ping.scanner

import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import ir.dicode.ping.data.AppRepository
import ir.dicode.ping.net.TelegramChannelCrawler
import ir.dicode.ping.util.RuntimeTuning
import ir.dicode.ping.vpn.DicodeVpnService
import ir.dicode.ping.vpn.VpnStateStore
import ir.dicode.ping.vpn.VpnStatus
import ir.dicode.ping.xray.CoreBridge
import ir.dicode.ping.xray.XrayConfigBuilder
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONObject

enum class ScannerStage { IDLE, CONNECTING, CRAWLING, DISCONNECTING, PROBING, SAVING, DONE, ENRICHING, ENRICHED, FAILED, STOPPED }

data class ScannerState(
    val stage: ScannerStage = ScannerStage.IDLE,
    val progress: Int = 0,
    val done: Int = 0,
    val total: Int = 0,
    val alive: Int = 0,
    val etaSeconds: Long? = null,
    val log: List<String> = emptyList(),
    val outputLog: List<String> = emptyList(),
    val result: String = "",
    val stopRequested: Boolean = false,
    val enrichmentPending: Boolean = false,
) {
    val running: Boolean get() = stage in setOf(
        ScannerStage.CONNECTING,
        ScannerStage.CRAWLING,
        ScannerStage.DISCONNECTING,
        ScannerStage.PROBING,
        ScannerStage.SAVING,
        ScannerStage.ENRICHING,
    )
}

/**
 * Application-owned scanner pipeline.
 *
 * The scanner follows a strict transaction:
 * 1) require the dashboard's already verified dicodePing Xray VPN,
 * 2) collect and persist Telegram candidates,
 * 3) fully stop the bootstrap VPN,
 * 4) run bounded parallel native Xray HTTP probes,
 * 5) atomically replace the single SUB source.
 */
class ScannerCoordinator private constructor(private val context: Context) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val repo = AppRepository.get(context)
    private val stop = AtomicBoolean(false)
    private val _state = MutableStateFlow(ScannerState())
    val state: StateFlow<ScannerState> = _state.asStateFlow()
    private var job: Job? = null

    @Synchronized
    fun start(name: String = "SUB", rank1: Int = 8, rank2: Int = 9) {
        if (job?.isActive == true) return
        stop.set(false)
        _state.value = ScannerState(
            stage = ScannerStage.CONNECTING,
            progress = 1,
            log = listOf("Waiting for the dashboard's verified VPN connection"),
        )
        job = scope.launch {
            try {
                run("SUB", normalizeLimit(rank1, 8), normalizeLimit(rank2, 9))
            } catch (cancelled: CancellationException) {
                update(
                    ScannerStage.STOPPED,
                    result = if (_state.value.alive > 0) {
                        "اسکن متوقف شد و ${_state.value.alive} سرور سالم ذخیره شد."
                    } else {
                        "اسکن متوقف شد؛ هنوز سرور سالمی ذخیره نشده بود."
                    },
                    log = "Scanner cancelled safely",
                )
            } catch (error: Throwable) {
                update(
                    ScannerStage.FAILED,
                    result = error.message ?: "Scanner failed",
                    log = "Scanner failed: ${error.javaClass.simpleName}",
                )
            } finally {
                try {
                    disconnectStrict(ignoreFailure = true)
                } catch (_: Throwable) {
                    // The terminal scanner state must still be published even when
                    // Android is already tearing down the VPN service.
                }
                synchronized(this@ScannerCoordinator) { job = null }
            }
        }
    }

    @Synchronized
    fun requestStop() {
        stop.set(true)
        _state.value = _state.value.copy(stopRequested = true)
        if (_state.value.stage !in setOf(ScannerStage.PROBING, ScannerStage.SAVING, ScannerStage.ENRICHING)) {
            job?.cancel(CancellationException("user requested stop"))
        }
    }

    suspend fun join() {
        job?.join()
    }

    private suspend fun run(name: String, rank1: Int, rank2: Int) {
        val core = CoreBridge(context)
        check(core.available()) { "Embedded Xray core is unavailable on this device/ABI." }
        val coreVersion = core.version().trim()
        check(coreVersion.isNotBlank() && !coreVersion.contains("unavailable", ignoreCase = true)) {
            "Embedded Xray core failed its runtime preflight."
        }
        update(ScannerStage.CONNECTING, progress = 1, log = "[XRAY][OK] Embedded core ready: ${mask(coreVersion)}")

        val channelPlan = readChannels(rank1, rank2)
        val channels = channelPlan.keys.toList()
        check(channels.isNotEmpty()) { "The canonical Telegram channel list is empty." }

        update(ScannerStage.CONNECTING, progress = 2, log = "Checking the dashboard VPN state")
        requireConnectedBootstrap()
        ensureRunning()

        val tuning = RuntimeTuning.detect(context, repo.settings.resourceMode)
        update(
            ScannerStage.CRAWLING,
            progress = 5,
            total = channels.size,
            done = 0,
            log = "[CONNECT][OK] Bootstrap VPN verified; crawling ${channels.size} Telegram channels",
        )
        update(
            ScannerStage.CRAWLING,
            progress = 5,
            log = "[CONNECT][ROUTE] Telegram uses Xray SOCKS5 127.0.0.1:${XrayConfigBuilder.SCANNER_SOCKS_PORT} with proxy-side DNS",
        )
        val crawlFound = AtomicInteger(0)
        val crawlTarget = 180
        val crawled = withTimeoutOrNull(CRAWL_TIMEOUT_MS) {
            try {
                TelegramChannelCrawler.crawl(
                    channels = channels,
                    maxWorkers = tuning.crawlWorkers.coerceIn(3, 8),
                    perChannelLimits = channelPlan,
                    progress = { done, total, channel ->
                        val channelRatio = done.coerceAtLeast(0).toDouble() / total.coerceAtLeast(1)
                        val configRatio = crawlFound.get().toDouble() / crawlTarget
                        val phaseRatio = (channelRatio * 0.70 + configRatio * 0.30).coerceIn(0.0, 1.0)
                        update(
                            stage = ScannerStage.CRAWLING,
                            progress = 5 + (phaseRatio * 40).toInt(),
                            done = done,
                            total = total,
                            log = if (channel.isBlank()) null else "[TG][STEP] ${mask(channel)}",
                        )
                    },
                    onResult = { result, done, total ->
                        if (result.ok && result.picked > 0) crawlFound.addAndGet(result.picked)
                        val channelRatio = done.coerceAtLeast(0).toDouble() / total.coerceAtLeast(1)
                        val configRatio = crawlFound.get().toDouble() / crawlTarget
                        val phaseRatio = (channelRatio * 0.70 + configRatio * 0.30).coerceIn(0.0, 1.0)
                        val message = if (result.ok) {
                            "[TG][OK] $done/$total @${mask(result.channel)} " +
                                "configs=${result.picked}/${result.found} host=t.me ${result.elapsedMs}ms"
                        } else {
                            "[TG][ERR] $done/$total @${mask(result.channel)} ${result.error.takeLast(220)}"
                        }
                        update(
                            stage = ScannerStage.CRAWLING,
                            progress = 5 + (phaseRatio * 40).toInt(),
                            done = done.coerceAtLeast(0),
                            total = total,
                            log = message,
                            output = if (result.ok && result.picked > 0) {
                                "[FOUND] @${mask(result.channel)} • ${result.picked}/${result.found} configs"
                            } else null,
                        )
                    },
                    maxUniqueConfigs = crawlTarget,
                    minimumChannelsBeforeTarget = 36,
                )
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Throwable) {
                update(
                    ScannerStage.CRAWLING,
                    progress = 44,
                    log = "[TG][WARN] Live crawl failed: ${mask(error.message ?: error.javaClass.simpleName)}",
                )
                emptyList()
            }
        }.orEmpty()
        ensureRunning()
        if (crawled.isNotEmpty()) {
            update(
                ScannerStage.CRAWLING,
                progress = 45,
                log = "[TG][DONE] collected=${crawled.size} unique configs from t.me",
            )
        }
        val configs = crawled.ifEmpty {
            loadFreshStage1Cache()?.also {
                update(ScannerStage.CRAWLING, progress = 45, log = "[TG][CACHE] Telegram was unavailable; using ${it.size} recent raw candidates")
            }.orEmpty()
        }
        check(configs.isNotEmpty()) {
            context.getString(ir.dicode.ping.R.string.scanner_telegram_unreachable)
        }

        atomicWrite(
            context.filesDir.resolve("scanner-stage1-raw.txt"),
            configs.joinToString("\n", postfix = "\n"),
        )
        atomicWrite(
            context.filesDir.resolve("scanner-stage1-meta.json"),
            JSONObject()
                .put("candidateCount", configs.size)
                .put("rank1Limit", rank1)
                .put("rank2Limit", rank2)
                .put("channelCount", channels.size)
                .put("savedAtEpochMs", System.currentTimeMillis())
                .toString(2),
        )
        update(
            ScannerStage.CRAWLING,
            progress = 46,
            log = "Saved ${configs.size} raw candidates before VPN shutdown",
        )

        update(ScannerStage.DISCONNECTING, progress = 48, log = "Stopping bootstrap VPN before native probes")
        disconnectStrict(ignoreFailure = false)
        ensureRunning()

        update(ScannerStage.PROBING, progress = 50, done = 0, total = configs.size, log = "Running bounded parallel real Xray HTTP probes")
        val imported = withTimeout(PROBE_TIMEOUT_MS) {
            repo.importScannerConfigs(
            configs = configs,
            requestedName = name,
            stopRequested = { stop.get() },
            onSaving = {
                update(ScannerStage.SAVING, progress = 97, log = "Committing the verified SUB transaction")
            },
            onProgress = { done, total, alive ->
                update(
                    stage = ScannerStage.PROBING,
                    progress = 50 + if (total > 0) done * 45 / total else 0,
                    done = done,
                    total = total,
                    alive = alive,
                )
            },
            )
        }
        val healthy = imported.filter { it.healthy }
        if (stop.get()) {
            update(
                ScannerStage.STOPPED,
                alive = healthy.size,
                result = if (healthy.isEmpty()) {
                    "اسکن متوقف شد؛ هنوز سرور سالمی ذخیره نشده بود."
                } else {
                    "اسکن متوقف شد و ${healthy.size} سرور سالم ذخیره شد."
                },
                log = "Verified partial results committed",
                enrichmentPending = healthy.isNotEmpty(),
            )
            return
        }
        check(healthy.isNotEmpty()) { "No config passed the real Xray HTTP probe." }
        healthy.take(40).forEach { server ->
            update(
                ScannerStage.SAVING,
                alive = healthy.size,
                output = "[OK] ${server.pingMs ?: 0} ms • ${mask(server.name)} • ${server.protocol}",
            )
        }
        update(
            ScannerStage.DONE,
            progress = 100,
            done = configs.size,
            total = configs.size,
            alive = healthy.size,
            result = "${healthy.size} healthy servers were saved in SUB.",
            log = "Scanner transaction completed",
            output = "[DONE] SUB updated with ${healthy.size} healthy servers",
            enrichmentPending = healthy.isNotEmpty(),
        )
    }

    /**
     * optional post-save ping + location enrichment.
     *
     * Called by the UI when the user accepts the post-save modal. Re-probes
     * the persisted scanner records with a bounded parallel pool, force-
     * refreshes geolocation, and atomically commits the enriched rows.
     */
    @Synchronized
    fun enrichSavedRecords() {
        if (job?.isActive == true) return
        stop.set(false)
        _state.value = _state.value.copy(
            stage = ScannerStage.ENRICHING,
            progress = 0,
            done = 0,
            total = 0,
            stopRequested = false,
            result = "در حال محاسبه پینگ و لوکیشن سرورهای ذخیره‌شده…",
            log = listOf("[ENRICH][START] re-probing scanner SUB with fresh ping+geo"),
        )
        job = scope.launch {
            try {
                val enriched = repo.enrichScannerRecords(
                    stopRequested = { stop.get() },
                    onProgress = { done, total ->
                        update(
                            stage = ScannerStage.ENRICHING,
                            progress = if (total > 0) (done * 100 / total) else 0,
                            done = done,
                            total = total,
                        )
                    },
                )
                update(
                    ScannerStage.ENRICHED,
                    progress = 100,
                    done = enriched.size,
                    total = enriched.size,
                    alive = enriched.count { it.healthy },
                    result = "پینگ و لوکیشن ${enriched.size} سرور به‌روزرسانی شد.",
                    log = "[ENRICH][DONE] scanner SUB ping and location refreshed",
                    output = "[DONE] enriched ${enriched.size} scanner servers",
                    enrichmentPending = false,
                )
            } catch (cancelled: CancellationException) {
                update(
                    ScannerStage.ENRICHED,
                    result = "محاسبه پینگ و لوکیشن متوقف شد.",
                    log = "Enrichment cancelled by user",
                    enrichmentPending = false,
                )
            } catch (error: Throwable) {
                update(
                    ScannerStage.FAILED,
                    result = error.message ?: "Enrichment failed",
                    log = "Enrichment failed: ${error.javaClass.simpleName}",
                    enrichmentPending = false,
                )
            } finally {
                synchronized(this@ScannerCoordinator) { job = null }
            }
        }
    }

    private suspend fun requireConnectedBootstrap() {
        val state = VpnStateStore.state.value
        check(state.status == VpnStatus.CONNECTED && state.serverId.isNotBlank()) {
            "برای شروع اسکن ابتدا از صفحه خانه به یک سرور dicodePing وصل شوید."
        }
        // CONNECTED is published by DicodeVpnService only after the Xray core
        // is running and a real HTTP request succeeds through the tunnel.
        delay(250)
        ensureRunning()
        val confirmed = VpnStateStore.state.value
        check(confirmed.status == VpnStatus.CONNECTED && confirmed.serverId == state.serverId) {
            "اتصال VPN پیش از شروع دریافت تلگرام قطع شد؛ کانفیگ و اینترنت را بررسی کنید."
        }
        update(
            ScannerStage.CONNECTING,
            progress = 22,
            log = "[CONNECT][OK] Dashboard Xray VPN is connected and HTTP-verified",
        )
    }

    private suspend fun disconnectStrict(ignoreFailure: Boolean) {
        if (VpnStateStore.state.value.status == VpnStatus.DISCONNECTED) return
        val stopSent = runCatching {
            context.startService(Intent(context, DicodeVpnService::class.java).setAction(DicodeVpnService.ACTION_STOP))
        }.isSuccess
        if (!stopSent && !ignoreFailure) error("Could not request bootstrap VPN shutdown.")
        val disconnected = runCatching {
            withTimeout(DISCONNECT_TIMEOUT_MS) {
                VpnStateStore.state.first { it.status == VpnStatus.DISCONNECTED }
            }
        }.isSuccess
        if (!disconnected && !ignoreFailure) {
            error("contaminationRisk: bootstrap VPN did not stop; probes were not started.")
        }
    }

    private fun readChannels(rank1: Int, rank2: Int): Map<String, Int> {
        val payload = context.assets.open("channels.json").bufferedReader().use { it.readText() }
        val rows = JSONObject(payload).getJSONArray("channels")
        val result = linkedMapOf<String, Int>()
        for (index in 0 until rows.length()) {
            val row = rows.getJSONObject(index)
            result[row.getString("name")] = if (row.getInt("rank") == 1) rank1 else rank2
        }
        return result
    }

    private fun loadFreshStage1Cache(): List<String>? {
        val file = context.filesDir.resolve("scanner-stage1-raw.txt")
        if (!file.isFile || System.currentTimeMillis() - file.lastModified() > STAGE1_CACHE_MAX_AGE_MS) return null
        return file.readLines(Charsets.UTF_8)
            .asSequence()
            .map(String::trim)
            .filter(String::isNotBlank)
            .distinct()
            .take(MAX_CACHED_CANDIDATES)
            .toList()
            .takeIf { it.isNotEmpty() }
    }

    private fun atomicWrite(target: File, content: String) {
        target.parentFile?.mkdirs()
        val temporary = File(target.parentFile, ".${target.name}.${System.nanoTime()}.tmp")
        temporary.writeText(content, Charsets.UTF_8)
        if (!temporary.renameTo(target)) {
            target.writeText(content, Charsets.UTF_8)
            temporary.delete()
        }
    }

    private fun ensureRunning() {
        if (stop.get()) throw CancellationException("scanner stopped")
    }

    @Synchronized
    private fun update(
        stage: ScannerStage,
        progress: Int = _state.value.progress,
        done: Int = _state.value.done,
        total: Int = _state.value.total,
        alive: Int = _state.value.alive,
        result: String = _state.value.result,
        log: String? = null,
        output: String? = null,
        enrichmentPending: Boolean = _state.value.enrichmentPending,
    ) {
        val previous = _state.value
        val safeProgress = if (stage == previous.stage && stage in setOf(ScannerStage.CRAWLING, ScannerStage.PROBING, ScannerStage.ENRICHING)) {
            maxOf(previous.progress, progress.coerceIn(0, 100))
        } else {
            progress.coerceIn(0, 100)
        }
        _state.value = previous.copy(
            stage = stage,
            progress = safeProgress,
            done = done,
            total = total,
            alive = alive,
            result = result,
            stopRequested = stop.get(),
            enrichmentPending = enrichmentPending,
            log = if (log == null) _state.value.log else (_state.value.log + log).takeLast(MAX_LOG_LINES),
            outputLog = if (output == null) _state.value.outputLog else (_state.value.outputLog + output).takeLast(MAX_OUTPUT_LINES),
        )
    }

    private fun mask(value: String): String = value.take(48).replace(Regex("[?&#].*"), "")

    companion object {
        private const val DISCONNECT_TIMEOUT_MS = 18_000L
        private const val CRAWL_TIMEOUT_MS = 4 * 60_000L
        private const val PROBE_TIMEOUT_MS = 14 * 60_000L
        private const val STAGE1_CACHE_MAX_AGE_MS = 12 * 60 * 60_000L
        private const val MAX_CACHED_CANDIDATES = 180
        private const val MAX_LOG_LINES = 220
        private const val MAX_OUTPUT_LINES = 140
        @SuppressLint("StaticFieldLeak")
        @Volatile private var instance: ScannerCoordinator? = null

        fun get(context: Context): ScannerCoordinator = instance ?: synchronized(this) {
            instance ?: ScannerCoordinator(context.applicationContext).also { instance = it }
        }

        fun normalizeLimit(value: Int, fallback: Int): Int = if (value in 1..20) value else fallback
        fun normalizeLimit(value: Int): Int = normalizeLimit(value, 3)
    }
}
