package ir.dicode.ping.scanner

import android.content.Context
import android.content.Intent
import android.net.VpnService
import androidx.core.content.ContextCompat
import ir.dicode.ping.data.AppRepository
import ir.dicode.ping.data.ServerRecord
import ir.dicode.ping.net.TelegramChannelCrawler
import ir.dicode.ping.util.RuntimeTuning
import ir.dicode.ping.vpn.DicodeVpnService
import ir.dicode.ping.vpn.VpnStateStore
import ir.dicode.ping.vpn.VpnStatus
import ir.dicode.ping.xray.CoreBridge
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean
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

enum class ScannerStage { IDLE, CONNECTING, CRAWLING, DISCONNECTING, PROBING, SAVING, DONE, FAILED, STOPPED }

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
) {
    val running: Boolean get() = stage in setOf(
        ScannerStage.CONNECTING,
        ScannerStage.CRAWLING,
        ScannerStage.DISCONNECTING,
        ScannerStage.PROBING,
        ScannerStage.SAVING,
    )
}

/**
 * Application-owned scanner pipeline.
 *
 * The scanner follows a strict transaction:
 * 1) connect dicodePing's verified Xray VPN,
 * 2) collect and persist Telegram candidates,
 * 3) fully stop the bootstrap VPN,
 * 4) run serialized native Xray HTTP probes,
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
            log = listOf("Preparing dicodePing bootstrap VPN"),
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
        if (_state.value.stage !in setOf(ScannerStage.PROBING, ScannerStage.SAVING)) {
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

        update(ScannerStage.CONNECTING, progress = 2, log = "Selecting a verified automatic bootstrap server")
        connectBootstrap()
        ensureRunning()

        val tuning = RuntimeTuning.detect(context)
        update(
            ScannerStage.CRAWLING,
            progress = 5,
            total = channels.size,
            done = 0,
            log = "[CONNECT][OK] Bootstrap VPN verified; crawling ${channels.size} Telegram channels",
        )
        val crawled = withTimeoutOrNull(CRAWL_TIMEOUT_MS) {
            try {
                TelegramChannelCrawler.crawl(
                    channels = channels,
                    maxWorkers = tuning.crawlWorkers.coerceIn(2, 4),
                    perChannelLimits = channelPlan,
                    progress = { done, total, channel ->
                        update(
                            stage = ScannerStage.CRAWLING,
                            progress = 5 + if (total > 0) done * 40 / total else 0,
                            done = done,
                            total = total,
                            log = if (channel.isBlank()) null else "[TG][STEP] ${mask(channel)}",
                        )
                    },
                    onResult = { result, done, total ->
                        val message = if (result.ok) {
                            "[TG][OK] $done/$total @${mask(result.channel)} " +
                                "configs=${result.picked}/${result.found} host=${result.previewHost} ${result.elapsedMs}ms"
                        } else {
                            "[TG][ERR] $done/$total @${mask(result.channel)} ${result.error.takeLast(220)}"
                        }
                        update(
                            stage = ScannerStage.CRAWLING,
                            progress = 5 + if (total > 0) done.coerceAtLeast(0) * 40 / total else 0,
                            done = done.coerceAtLeast(0),
                            total = total,
                            log = message,
                            output = if (result.ok && result.picked > 0) {
                                "[FOUND] @${mask(result.channel)} • ${result.picked}/${result.found} configs"
                            } else null,
                        )
                    },
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
        val configs = crawled.ifEmpty {
            loadFreshStage1Cache()?.also {
                update(ScannerStage.CRAWLING, progress = 45, log = "[TG][CACHE] Telegram was unavailable; using ${it.size} recent raw candidates")
            }.orEmpty()
        }
        check(configs.isNotEmpty()) { "No valid Xray configs were collected from Telegram and no fresh scanner cache is available." }

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

        update(ScannerStage.PROBING, progress = 50, done = 0, total = configs.size, log = "Running serialized real Xray HTTP probes")
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
        )
    }

    private suspend fun connectBootstrap() {
        check(VpnService.prepare(context) == null) {
            "مجوز VPN صادر نشده است؛ اسکن را دوباره بزنید و مجوز سیستم را تایید کنید."
        }
        disconnectStrict(ignoreFailure = true)

        val candidates = linkedMapOf<String, ServerRecord>()
        (repo.connectionCandidates(8, primaryOnly = true) + repo.connectionCandidates(8)).forEach { candidates.putIfAbsent(it.id, it) }
        check(candidates.isNotEmpty()) { "No verified automatic bootstrap server is available." }

        var lastError = "No bootstrap candidate reached the connected state."
        candidates.values.forEachIndexed { index, server ->
            ensureRunning()
            update(
                ScannerStage.CONNECTING,
                progress = 2 + ((index + 1) * 3).coerceAtMost(18),
                log = "Bootstrap attempt ${index + 1}/${candidates.size}: ${mask(server.name)}",
            )
            val settings = repo.settings
            val intent = Intent(context, DicodeVpnService::class.java)
                .putExtra(DicodeVpnService.EXTRA_CONFIG, server.raw)
                .putExtra(DicodeVpnService.EXTRA_CORE_ID, "xray")
                .putExtra(DicodeVpnService.EXTRA_SERVER_ID, server.id)
                .putExtra(DicodeVpnService.EXTRA_NAME, server.name)
                .putExtra(DicodeVpnService.EXTRA_BYPASS_DOMAINS, settings.bypassDomains)
                .putStringArrayListExtra(DicodeVpnService.EXTRA_BYPASS_APPS, arrayListOf())
                .putExtra(DicodeVpnService.EXTRA_PER_APP_MODE, "allowlist")
                .putStringArrayListExtra(DicodeVpnService.EXTRA_PER_APP_PACKAGES, arrayListOf(context.packageName))
                .putExtra(DicodeVpnService.EXTRA_VPN_SHARING_USB, false)
                .putExtra(DicodeVpnService.EXTRA_VPN_SHARING_HOTSPOT, false)

            val started = runCatching { ContextCompat.startForegroundService(context, intent) }
            if (started.isFailure) {
                lastError = started.exceptionOrNull()?.message ?: "Cannot start the VPN foreground service."
                return@forEachIndexed
            }

            val outcome = runCatching {
                val state = withTimeout(CONNECTION_TIMEOUT_MS) {
                    VpnStateStore.state.first {
                        it.serverId == server.id && it.status in setOf(VpnStatus.CONNECTED, VpnStatus.ERROR)
                    }
                }
                check(state.status == VpnStatus.CONNECTED) {
                    state.message.ifBlank { "Bootstrap VPN failed" }
                }
                // DicodeVpnService publishes CONNECTED only after a real HTTP probe,
                // so no single Telegram channel is allowed to invalidate a healthy VPN.
                delay(300)
                ensureRunning()
            }
            if (outcome.isSuccess) {
                update(ScannerStage.CONNECTING, progress = 22, log = "[CONNECT][OK] Bootstrap VPN connected and HTTP-verified")
                return
            }
            lastError = outcome.exceptionOrNull()?.message ?: lastError
            disconnectStrict(ignoreFailure = true)
        }
        error(lastError)
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
    ) {
        _state.value = _state.value.copy(
            stage = stage,
            progress = progress.coerceIn(0, 100),
            done = done,
            total = total,
            alive = alive,
            result = result,
            stopRequested = stop.get(),
            log = if (log == null) _state.value.log else (_state.value.log + log).takeLast(MAX_LOG_LINES),
            outputLog = if (output == null) _state.value.outputLog else (_state.value.outputLog + output).takeLast(MAX_OUTPUT_LINES),
        )
    }

    private fun mask(value: String): String = value.take(48).replace(Regex("[?&#].*"), "")

    companion object {
        private const val CONNECTION_TIMEOUT_MS = 35_000L
        private const val DISCONNECT_TIMEOUT_MS = 18_000L
        private const val CRAWL_TIMEOUT_MS = 8 * 60_000L
        private const val PROBE_TIMEOUT_MS = 14 * 60_000L
        private const val STAGE1_CACHE_MAX_AGE_MS = 12 * 60 * 60_000L
        private const val MAX_CACHED_CANDIDATES = 180
        private const val MAX_LOG_LINES = 220
        private const val MAX_OUTPUT_LINES = 140
        @Volatile private var instance: ScannerCoordinator? = null

        fun get(context: Context): ScannerCoordinator = instance ?: synchronized(this) {
            instance ?: ScannerCoordinator(context.applicationContext).also { instance = it }
        }

        fun normalizeLimit(value: Int, fallback: Int): Int = if (value in 1..20) value else fallback
        fun normalizeLimit(value: Int): Int = normalizeLimit(value, 3)
    }
}
