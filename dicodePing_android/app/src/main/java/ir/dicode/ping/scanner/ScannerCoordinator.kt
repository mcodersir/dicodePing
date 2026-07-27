package ir.dicode.ping.scanner

import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat
import ir.dicode.ping.data.AppRepository
import ir.dicode.ping.net.TelegramChannelCrawler
import ir.dicode.ping.util.RuntimeTuning
import ir.dicode.ping.vpn.DicodeVpnService
import ir.dicode.ping.vpn.VpnStateStore
import ir.dicode.ping.vpn.VpnStatus
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.max
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout
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
 * Application-owned scanner session. It is independent of Fragment and
 * Activity recreation; ScannerService keeps the process foreground-visible.
 */
class ScannerCoordinator private constructor(private val context: Context) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val repo = AppRepository.get(context)
    private val stop = AtomicBoolean(false)
    private val _state = MutableStateFlow(ScannerState())
    val state: StateFlow<ScannerState> = _state.asStateFlow()
    private var job: Job? = null

    @Synchronized
    fun start(name: String = "SUB", rank1: Int = 3, rank2: Int = 3) {
        if (job?.isActive == true) return
        stop.set(false)
        job = scope.launch {
            runCatching { run("SUB", normalizeLimit(rank1), normalizeLimit(rank2)) }
                .onFailure { error ->
                    if (error is CancellationException || stop.get()) {
                        update(ScannerStage.STOPPED, result = "اسکن متوقف شد؛ هنوز سرور سالمی پیدا نشده بود.")
                    } else {
                        update(ScannerStage.FAILED, result = error.message ?: "Scanner failed")
                    }
                    disconnectStrict(ignoreFailure = true)
                }
        }
    }

    fun requestStop() {
        stop.set(true)
        _state.value = _state.value.copy(stopRequested = true)
        if (_state.value.stage != ScannerStage.PROBING) {
            job?.cancel(CancellationException("user requested stop"))
        }
    }

    suspend fun join() {
        job?.join()
    }

    private suspend fun run(name: String, rank1: Int, rank2: Int) {
        update(ScannerStage.CONNECTING, log = "Selecting the best primary-source server")
        val channelPlan = readChannels(rank1, rank2)
        val channels = channelPlan.keys.toList()
        check(channels.isNotEmpty()) { "The canonical Telegram channel list is empty." }
        connectBootstrap(channels.first())
        ensureRunning()

        val tuning = RuntimeTuning.detect(context)
        val started = System.nanoTime()
        update(ScannerStage.CRAWLING, total = channels.size, log = "Crawling canonical Xray channels")
        val configs = TelegramChannelCrawler.crawl(channels, tuning.crawlWorkers, channelPlan) { done, total, channel ->
            _state.value = _state.value.copy(
                progress = if (total > 0) done * 45 / total else 0,
                done = done,
                total = total,
                etaSeconds = null,
                log = (_state.value.log + "Fetched ${mask(channel)}").takeLast(MAX_LOG_LINES),
            )
        }
        ensureRunning()
        check(configs.isNotEmpty()) { "No valid Xray configs were collected." }

        update(ScannerStage.DISCONNECTING, progress = 48, log = "Stopping bootstrap before probes")
        disconnectStrict(ignoreFailure = false)
        ensureRunning()

        update(ScannerStage.PROBING, progress = 50, total = configs.size, log = "Running real Xray HTTP probes")
        val probeStarted = System.nanoTime()
        val imported = repo.importScannerConfigs(
            configs,
            name,
            stopRequested = { stop.get() },
            onSaving = {
                update(ScannerStage.SAVING, progress = 97, log = "Committing verified results")
            },
            onProgress = { done, total, alive ->
                _state.value = _state.value.copy(
                    progress = 50 + if (total > 0) done * 45 / total else 0,
                    done = done,
                    total = total,
                    alive = alive,
                    etaSeconds = null,
                )
            },
        )
        val healthy = imported.filter { it.healthy }
        if (stop.get()) {
            update(
                ScannerStage.STOPPED,
                progress = _state.value.progress,
                alive = healthy.size,
                result = if (healthy.isEmpty()) {
                    "اسکن متوقف شد؛ هنوز سرور سالمی پیدا نشده بود."
                } else {
                    "اسکن متوقف شد و ${healthy.size} سرور سالم ذخیره شد."
                },
                log = "Probe submission stopped; verified partial results committed",
            )
            return
        }
        check(healthy.isNotEmpty()) { "No config passed the Xray HTTP probe." }
        update(
            ScannerStage.DONE,
            progress = 100,
            done = _state.value.done,
            total = configs.size,
            alive = healthy.size,
            result = "${healthy.size} healthy servers were saved.",
            log = "Scanner transaction completed",
        )
    }

    private suspend fun connectBootstrap(validationChannel: String) {
        val candidates = repo.primaryAutomaticCandidates(5)
        check(candidates.isNotEmpty()) { "No healthy primary-source bootstrap server is available." }
        var lastError = "No bootstrap candidate passed validation."
        for (server in candidates) {
            ensureRunning()
            update(ScannerStage.CONNECTING, log = "Validating bootstrap ${mask(server.name)}")
            val settings = repo.settings
            val intent = Intent(context, DicodeVpnService::class.java)
                .putExtra(DicodeVpnService.EXTRA_CONFIG, server.raw)
                .putExtra(DicodeVpnService.EXTRA_SERVER_ID, server.id)
                .putExtra(DicodeVpnService.EXTRA_NAME, server.name)
                .putExtra(DicodeVpnService.EXTRA_BYPASS_DOMAINS, settings.bypassDomains)
                .putStringArrayListExtra(DicodeVpnService.EXTRA_BYPASS_APPS, arrayListOf<String>())
                // Route the crawler itself through the bootstrap TUN. The native
                // core protects its own sockets, so this does not create a loop.
                .putExtra(DicodeVpnService.EXTRA_PER_APP_MODE, "allowlist")
                .putStringArrayListExtra(
                    DicodeVpnService.EXTRA_PER_APP_PACKAGES,
                    arrayListOf(context.packageName),
                )
                .putExtra(DicodeVpnService.EXTRA_VPN_SHARING_USB, false)
                .putExtra(DicodeVpnService.EXTRA_VPN_SHARING_HOTSPOT, false)
            ContextCompat.startForegroundService(context, intent)
            val outcome = runCatching {
                val connected = withTimeout(CONNECTION_TIMEOUT_MS) {
                    VpnStateStore.state.first {
                        it.serverId == server.id &&
                            (it.status == VpnStatus.CONNECTED || it.status == VpnStatus.ERROR)
                    }
                }
                check(connected.status == VpnStatus.CONNECTED) {
                    connected.message.ifBlank { "Bootstrap VPN failed" }
                }
                ensureRunning()
                check(TelegramChannelCrawler.fetchChannel(validationChannel, 1).ok) {
                    "Telegram Preview validation failed inside the bootstrap VPN."
                }
            }
            if (outcome.isSuccess) return
            lastError = outcome.exceptionOrNull()?.message ?: lastError
            disconnectStrict(ignoreFailure = false)
        }
        error(lastError)
    }

    private suspend fun disconnectStrict(ignoreFailure: Boolean) {
        context.startService(Intent(context, DicodeVpnService::class.java).setAction(DicodeVpnService.ACTION_STOP))
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
            val limit = if (row.getInt("rank") == 1) rank1 else rank2
            result[row.getString("name")] = limit
        }
        return result.entries.associate { it.key to it.value }
    }

    private fun ensureRunning() {
        if (stop.get()) throw CancellationException("scanner stopped")
    }

    private fun update(
        stage: ScannerStage,
        progress: Int = _state.value.progress,
        done: Int = _state.value.done,
        total: Int = _state.value.total,
        alive: Int = _state.value.alive,
        result: String = _state.value.result,
        log: String? = null,
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
        )
    }

    private fun mask(value: String): String = value.take(48).replace(Regex("[?&#].*"), "")

    companion object {
        private const val CONNECTION_TIMEOUT_MS = 45_000L
        private const val DISCONNECT_TIMEOUT_MS = 15_000L
        private const val MAX_LOG_LINES = 120
        @Volatile private var instance: ScannerCoordinator? = null
        fun get(context: Context): ScannerCoordinator = instance ?: synchronized(this) {
            instance ?: ScannerCoordinator(context.applicationContext).also { instance = it }
        }
        fun normalizeLimit(value: Int): Int = if (value in 1..20) value else 3
    }
}
