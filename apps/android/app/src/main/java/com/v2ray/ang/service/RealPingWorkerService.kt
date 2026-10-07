package com.v2ray.ang.service

import android.content.Context
import com.v2ray.ang.core.CoreConfigManager
import com.v2ray.ang.core.CoreNativeManager
import com.v2ray.ang.dto.RealPingEvent
import com.v2ray.ang.enums.EConfigType
import com.v2ray.ang.extension.isComplexType
import com.v2ray.ang.extension.isNotNullEmpty
import com.v2ray.ang.handler.MmkvManager
import com.v2ray.ang.handler.SettingsManager
import com.v2ray.ang.handler.SpeedtestManager
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineName
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.asCoroutineDispatcher
import kotlinx.coroutines.isActive
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.joinAll
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicInteger

internal object RealPingExecutionLimiter {
    private val customConfigMutex = Mutex()

    suspend fun <T> run(configType: EConfigType, block: () -> T): T {
        // Custom profiles bypass speed-test trimming and start complete Xray configs.
        // Parallel teardown can abort the native probe process, so serialize their
        // JNI measurements globally across batches.
        return if (configType == EConfigType.CUSTOM) {
            customConfigMutex.withLock { block() }
        } else {
            block()
        }
    }
}

/** The single real-latency path shared by the main list and the server pool. */
internal object RealPingProbe {
    suspend fun measure(context: Context, guid: String, batch: String = java.util.UUID.randomUUID().toString()): Long {
        val failure = -1L
        val config = MmkvManager.decodeServerConfig(guid) ?: return failure

        // Keep the same fast reachability gate used by the main Real Ping action.
        if (!config.configType.isComplexType()
            && config.configType != EConfigType.HYSTERIA2
            && config.configType != EConfigType.WIREGUARD
            && config.alpn?.startsWith("h3") != true
            && config.server.isNotNullEmpty()
            && config.serverPort?.toIntOrNull() != null
        ) {
            val tcpTime = SpeedtestManager.socketConnectTime(config.server.orEmpty(), config.serverPort.orEmpty().toInt(), 1000)
            if (tcpTime <= -1L) return failure
        }

        val configResult = CoreConfigManager.getV2rayConfig4Speedtest(context, guid)
        if (!configResult.status) return failure
        return RealPingExecutionLimiter.run(config.configType) {
            CoreNativeManager.measureOutboundDelay(configResult.content, SettingsManager.getDelayTestUrl(), batch)
        }
    }
}

/**
 * Worker that runs a batch of real-ping tests independently.
 * Each batch owns its own CoroutineScope/dispatcher and can be cancelled separately.
 */
class RealPingWorkerService(
    private val context: Context,
    private val guids: List<String>,
    private val onlyTcp: Boolean = false,
    private val locationOnly: Boolean = false,
    private val sanctionsOnly: Boolean = false,
    private val onEvent: (RealPingEvent) -> Unit = {}
) {
    private val batch = java.util.UUID.randomUUID().toString()
    private val job = SupervisorJob()
    private val concurrency = SettingsManager.getRealPingConcurrency()
    private val dispatcher = Executors.newFixedThreadPool(if (onlyTcp) concurrency * 2 else concurrency).asCoroutineDispatcher()
    private val scope = CoroutineScope(job + dispatcher + CoroutineName("RealPingBatchWorker"))

    private val runningCount = AtomicInteger(0)
    private val totalCount = AtomicInteger(0)

    fun start() {
        val jobs = guids.map { guid ->
            totalCount.incrementAndGet()
            scope.launch {
                job.ensureActive()
                runningCount.incrementAndGet()
                try {
                    val sanctions = if (sanctionsOnly) startSanctionsCheck(guid) else null
                    val result = if (sanctionsOnly || locationOnly) -1L else if (onlyTcp) startTcping(guid) else startRealPing(guid)
                    val location = if (locationOnly) {
                        SpeedtestManager.getServerLocationInfo(MmkvManager.decodeServerConfig(guid)?.server)
                    } else null
                    if (scope.isActive) {
                        onEvent(RealPingEvent.Result(
                            guid, result, location?.country, location?.ipAddress,
                            sanctions?.first, sanctions?.second ?: 0, SANCTIONS_SERVICES.size
                        ))
                    }
                } catch (cancelled: CancellationException) {
                    throw cancelled
                } catch (_: Exception) {
                    // A failed profile does not cancel other measurements.
                } finally {
                    val count = totalCount.decrementAndGet()
                    val left = runningCount.decrementAndGet()
                    if (scope.isActive) {
                        onEvent(RealPingEvent.Progress("$left / $count"))
                    }
                }
            }
        }

        scope.launch {
            try {
                joinAll(*jobs.toTypedArray())
                if (isActive) {
                    onEvent(RealPingEvent.Finish("0"))
                }
            } catch (_: CancellationException) {
                // If cancelled, don't send finish event to avoid confusion
            } finally {
                close()
            }
        }
    }

    fun cancel() {
        job.cancel()
        kotlin.concurrent.thread(name = "DicodePingCancel") { CoreNativeManager.cancelOutboundDelays(batch) }
    }

    private fun close() {
        try {
            dispatcher.close()
        } catch (_: Throwable) {
            // ignore
        }
    }

    private suspend fun startRealPing(guid: String): Long = RealPingProbe.measure(context, guid, batch)

    private suspend fun startSanctionsCheck(guid: String): Triple<Boolean, Int, Int> {
        val config = MmkvManager.decodeServerConfig(guid) ?: return Triple(false, 0, 0)
        val configResult = CoreConfigManager.getV2rayConfig4Speedtest(context, guid)
        if (!configResult.status) return Triple(false, 0, 0)
        var passed = 0
        var strictFailed = false
        RealPingExecutionLimiter.run(config.configType) {
            SANCTIONS_SERVICES.forEach { service ->
                job.ensureActive()
                val delay = CoreNativeManager.measureOutboundDelay(configResult.content, service.url, batch)
                if (delay >= 0L) {
                    passed++
                } else if (service.strict) {
                    strictFailed = true
                }
            }
        }
        val total = SANCTIONS_SERVICES.size
        // Strict services are the most reliable sanctions indicators; the overall
        // pass ratio must also clear two thirds for an accessible verdict.
        val accessible = !strictFailed && passed * 3 >= total * 2
        return Triple(accessible, passed, total)
    }

    private companion object {
        data class SanctionService(val name: String, val url: String, val strict: Boolean)

        val SANCTIONS_SERVICES = listOf(
            SanctionService("Gemini", "https://gemini.google.com/", true),
            SanctionService("Google AI Studio", "https://aistudio.google.com/", true),
            SanctionService("ChatGPT", "https://chatgpt.com/", true),
            SanctionService("OpenAI API", "https://api.openai.com/", true),
            SanctionService("Docker Hub", "https://hub.docker.com/", true),
            SanctionService("YouTube", "https://www.youtube.com/", false),
            SanctionService("YouTube Studio", "https://studio.youtube.com/", false),
            SanctionService("Netflix", "https://www.netflix.com/", false),
            SanctionService("Spotify", "https://open.spotify.com/", false),
            SanctionService("Telegram Web", "https://web.telegram.org/k/", false),
            SanctionService("GitHub", "https://github.com/", false),
            SanctionService("Hugging Face", "https://huggingface.co/", false),
            SanctionService("Steam", "https://store.steampowered.com/", false),
            SanctionService("Figma", "https://www.figma.com/", false),
            SanctionService("Notion", "https://www.notion.so/", false),
            SanctionService("Medium", "https://medium.com/", false),
            SanctionService("Wikipedia", "https://www.wikipedia.org/", false),
            SanctionService("JetBrains", "https://www.jetbrains.com/", false)
        )
    }

    private fun startTcping(guid: String): Long {
        val retFailure = -1L

        val config = MmkvManager.decodeServerConfig(guid) ?: return retFailure
        if (!config.configType.isComplexType()
            && config.configType != EConfigType.HYSTERIA2
            && config.configType != EConfigType.WIREGUARD
            && config.alpn?.split(',')?.all { it.trim().startsWith("h3") } != true
            && config.server.isNotNullEmpty()
            && config.serverPort?.toIntOrNull() != null
        ) {
            val url = config.server.orEmpty()
            val port = config.serverPort.orEmpty().toInt()
            val tcpTime = SpeedtestManager.socketConnectTime(url, port, 1000)

            return tcpTime
        }

        return retFailure
    }
}
