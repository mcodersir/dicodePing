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
    fun detect(context: Context, mode: String = "optimized"): RuntimeProfile {
        val cpu = Runtime.getRuntime().availableProcessors().coerceAtLeast(1)
        val memoryMb = context.getSystemService(ActivityManager::class.java)
            ?.memoryClass
            ?.coerceAtLeast(128)
            ?: 256

        val lowMemory = memoryMb <= 256
        val midMemory = memoryMb <= 512
        val crawl = when {
            lowMemory -> 3
            midMemory -> 5
            else -> (cpu * 2).coerceIn(6, 8)
        }
        val probe = when {
            lowMemory -> 2
            midMemory -> 4
            else -> (cpu * 2).coerceIn(6, 16)
        }
        val professional = mode == "professional"
        return RuntimeProfile(
            cpuCores = cpu,
            memoryClassMb = memoryMb,
            downloadWorkers = if (professional) (if (lowMemory) 3 else 6) else (if (lowMemory) 2 else 4),
            crawlWorkers = (if (professional) crawl + 3 else crawl).coerceAtMost((cpu * (if (professional) 3 else 2)).coerceAtLeast(2)),
            dnsWorkers = (cpu * (if (professional) 4 else 3)).coerceIn(4, if (lowMemory) 8 else if (professional) 36 else 24),
            geoWorkers = (cpu * (if (professional) 3 else 2)).coerceIn(2, if (lowMemory) 4 else if (professional) 12 else 8),
            probeWorkers = (if (professional) probe + 4 else probe).coerceAtMost((cpu * (if (professional) 3 else 2)).coerceAtLeast(2)),
            retryWorkers = (probe / 3 + (if (professional) 2 else 0)).coerceIn(2, if (professional) 8 else 4),
            bufferSizeKiB = when {
                lowMemory -> 16
                midMemory -> 64
                memoryMb <= 1024 -> 128
                professional && memoryMb > 512 -> 512
                else -> 256
            },
        )
    }
}
