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
    suspend fun measure(context: Context, guid: String): Long {
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
            CoreNativeManager.measureOutboundDelay(configResult.content, SettingsManager.getDelayTestUrl())
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
                runningCount.incrementAndGet()
                try {
                    val sanctions = if (sanctionsOnly) startSanctionsCheck(guid) else null
                    val result = if (sanctionsOnly) -1L else if (onlyTcp) startTcping(guid) else startRealPing(guid)
                    val location = if (locationOnly) {
                        SpeedtestManager.getServerLocationInfo(MmkvManager.decodeServerConfig(guid)?.server)
                    } else null
                    if (scope.isActive) {
                        onEvent(RealPingEvent.Result(
                            guid, result, location?.country, location?.ipAddress,
                            sanctions?.first, sanctions?.second ?: 0, SANCTIONS_URLS.size
                        ))
                    }
                } catch (_: Throwable) {
                    // ignore
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
    }

    private fun close() {
        try {
            dispatcher.close()
        } catch (_: Throwable) {
            // ignore
        }
    }

    private suspend fun startRealPing(guid: String): Long = RealPingProbe.measure(context, guid)

    private suspend fun startSanctionsCheck(guid: String): Pair<Boolean, Int> {
        val config = MmkvManager.decodeServerConfig(guid) ?: return false to 0
        val configResult = CoreConfigManager.getV2rayConfig4Speedtest(context, guid)
        if (!configResult.status) return false to 0
        var passed = 0
        var googleAiPassed = false
        RealPingExecutionLimiter.run(config.configType) {
            SANCTIONS_URLS.forEachIndexed { index, url ->
                val delay = CoreNativeManager.measureOutboundDelay(configResult.content, url)
                if (delay >= 0L) {
                    passed++
                    if (index < 2) googleAiPassed = true
                }
            }
        }
        return (googleAiPassed && passed >= 3) to passed
    }

    private companion object {
        val SANCTIONS_URLS = listOf(
            "https://gemini.google.com/",
            "https://flow.google/",
            "https://firebase.google.com/",
            "https://dart.dev/",
            "https://flutter.dev/"
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
