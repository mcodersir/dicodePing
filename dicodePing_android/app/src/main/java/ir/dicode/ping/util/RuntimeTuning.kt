package ir.dicode.ping.util

import android.app.ActivityManager
import android.content.Context

data class RuntimeProfile(
    val cpuCores: Int,
    val memoryClassMb: Int,
    val downloadWorkers: Int,
    val crawlWorkers: Int,
    val dnsWorkers: Int,
    val geoWorkers: Int,
    val probeWorkers: Int,
    val retryWorkers: Int,
    val bufferSizeKiB: Int,
)

/** Resource limits shared by discovery, scanner and the embedded Xray core. */
object RuntimeTuning {
    fun detect(context: Context): RuntimeProfile {
        val cpu = Runtime.getRuntime().availableProcessors().coerceAtLeast(1)
        val memoryMb = context.getSystemService(ActivityManager::class.java)
            ?.memoryClass
            ?.coerceAtLeast(128)
            ?: 256

        val lowMemory = memoryMb <= 256
        val midMemory = memoryMb <= 512
        val crawl = when {
            lowMemory -> 2
            midMemory -> 3
            else -> (cpu * 2).coerceIn(4, 8)
        }
        val probe = when {
            lowMemory -> 2
            midMemory -> 4
            else -> (cpu * 2).coerceIn(6, 16)
        }
        return RuntimeProfile(
            cpuCores = cpu,
            memoryClassMb = memoryMb,
            downloadWorkers = if (lowMemory) 2 else 4,
            crawlWorkers = crawl.coerceAtMost((cpu * 2).coerceAtLeast(2)),
            dnsWorkers = (cpu * 3).coerceIn(4, if (lowMemory) 8 else 24),
            geoWorkers = (cpu * 2).coerceIn(2, if (lowMemory) 4 else 8),
            probeWorkers = probe.coerceAtMost((cpu * 2).coerceAtLeast(2)),
            retryWorkers = (probe / 3).coerceIn(2, 4),
            bufferSizeKiB = when {
                lowMemory -> 16
                midMemory -> 64
                memoryMb <= 1024 -> 128
                else -> 256
            },
        )
    }
}
