package ir.dicode.ping.net

import ir.dicode.ping.data.PingResult
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.Socket
import kotlin.math.roundToInt

object PingProbe {
    suspend fun probe(host: String, port: Int): PingResult = withContext(Dispatchers.IO) {
        val ip = runCatching { InetAddress.getByName(host).hostAddress.orEmpty() }.getOrDefault("")
        val values = mutableListOf<Double>()
        runCatching {
            val process = ProcessBuilder("/system/bin/ping", "-c", "3", "-W", "2", host).redirectErrorStream(true).start()
            val text = process.inputStream.bufferedReader().readText(); process.waitFor()
            Regex("time[=<]([0-9.]+)\\s*ms").findAll(text).forEach { values += it.groupValues[1].toDouble() }
        }
        if (values.isNotEmpty()) {
            val sorted = values.sorted(); return@withContext PingResult(sorted[sorted.size / 2].roundToInt(), "ICMP", ip)
        }
        val started = System.nanoTime()
        val ok = runCatching { Socket().use { it.connect(InetSocketAddress(host, port), 2500) }; true }.getOrDefault(false)
        val ms = ((System.nanoTime() - started) / 1_000_000L).toInt()
        PingResult(if (ok) ms else null, if (ok) "TCP" else "", ip)
    }
}
