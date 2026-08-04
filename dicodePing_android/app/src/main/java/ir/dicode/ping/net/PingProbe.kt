package ir.dicode.ping.net

import ir.dicode.ping.data.PingResult
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.Socket
import java.util.concurrent.TimeUnit
import kotlin.math.roundToInt

object PingProbe {
    suspend fun probe(host: String, port: Int): PingResult = withContext(Dispatchers.IO) {
        val ip = withTimeoutOrNull(DNS_TIMEOUT_MS) {
            runCatching { InetAddress.getByName(host).hostAddress.orEmpty() }.getOrDefault("")
        }.orEmpty()

        coroutineScope {
            val tcp = async(Dispatchers.IO) { tcpProbe(ip.ifBlank { host }, port) }
            val icmp = async(Dispatchers.IO) { icmpProbe(ip.ifBlank { host }) }
            val icmpMs = icmp.await()
            val tcpMs = tcp.await()
            when {
                icmpMs != null -> PingResult(icmpMs, "ICMP", ip)
                tcpMs != null -> PingResult(tcpMs, "TCP", ip)
                else -> PingResult(null, "", ip)
            }
        }
    }

    private fun tcpProbe(host: String, port: Int): Int? {
        val started = System.nanoTime()
        val ok = runCatching {
            Socket().use { it.connect(InetSocketAddress(host, port), TCP_TIMEOUT_MS) }
            true
        }.getOrDefault(false)
        if (!ok) return null
        return ((System.nanoTime() - started) / 1_000_000L).coerceAtLeast(1L).toInt()
    }

    private fun icmpProbe(host: String): Int? = runCatching {
        val process = ProcessBuilder(
            "/system/bin/ping", "-c", "1", "-W", "1", host,
        ).redirectErrorStream(true).start()
        if (!process.waitFor(ICMP_DEADLINE_MS, TimeUnit.MILLISECONDS)) {
            process.destroyForcibly()
            return@runCatching null
        }
        val text = process.inputStream.bufferedReader().use { it.readText() }
        Regex("time[=<]([0-9.]+)\\s*ms")
            .find(text)
            ?.groupValues
            ?.getOrNull(1)
            ?.toDoubleOrNull()
            ?.roundToInt()
    }.getOrNull()

    private const val DNS_TIMEOUT_MS = 1_500L
    private const val TCP_TIMEOUT_MS = 900
    private const val ICMP_DEADLINE_MS = 1_250L
}
