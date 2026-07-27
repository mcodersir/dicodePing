package ir.dicode.ping.core

import android.content.Context
import android.os.Build
import android.os.SystemClock
import ir.dicode.ping.util.AppLog
import java.io.File
import java.net.InetSocketAddress
import java.net.Socket
import java.util.ArrayDeque
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext

/**
 * Runs Aether/Usque from Android's read-only nativeLibraryDir.
 *
 * Android 10+ forbids execve() from the writable app home directory. The
 * release workflow therefore packages both helpers as lib*.so entries and
 * asks PackageManager to extract them into nativeLibraryDir, where executable
 * code shipped by the APK is allowed to run.
 */
class AndroidExternalCoreProcess(
    private val context: Context,
    val coreId: String,
) {
    val socksPort: Int = when (coreId) {
        "aether" -> 1819
        "warp" -> 1820
        else -> error("Unsupported external core: $coreId")
    }

    private var process: Process? = null
    private val runtimeDir = File(context.filesDir, "core-state/$coreId").apply { mkdirs() }
    private val outputTail = ArrayDeque<String>()

    private fun libraryName(): String = when (coreId) {
        "aether" -> "libaether.so"
        "warp" -> "libusque.so"
        else -> error("Unsupported external core: $coreId")
    }

    fun executable(): File = File(context.applicationInfo.nativeLibraryDir, libraryName())

    fun isBundled(): Boolean = executable().let { it.isFile && it.length() >= 500_000L }

    /** API-24-safe replacement for Process.isAlive(), which was added in API 26. */
    private fun Process.isAliveCompat(): Boolean {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) return isAlive
        return try {
            exitValue()
            false
        } catch (_: IllegalThreadStateException) {
            true
        }
    }

    /**
     * API-24-safe timed wait. Process.waitFor(timeout, unit) only exists from
     * API 26, so Android 7.x uses the documented exitValue polling contract.
     */
    private fun Process.waitForCompat(timeoutMillis: Long): Boolean {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            return waitFor(timeoutMillis, TimeUnit.MILLISECONDS)
        }
        val deadline = SystemClock.elapsedRealtime() + timeoutMillis.coerceAtLeast(0L)
        while (SystemClock.elapsedRealtime() < deadline) {
            if (!isAliveCompat()) return true
            val remaining = deadline - SystemClock.elapsedRealtime()
            try {
                Thread.sleep(minOf(50L, remaining.coerceAtLeast(1L)))
            } catch (_: InterruptedException) {
                Thread.currentThread().interrupt()
                return !isAliveCompat()
            }
        }
        return !isAliveCompat()
    }

    /** Gracefully stops on API 24/25 and escalates on API 26+. */
    private fun Process.stopCompat(graceMillis: Long = 2_000L) {
        runCatching { destroy() }
        if (waitForCompat(graceMillis)) return
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            runCatching { destroyForcibly() }
            waitForCompat(graceMillis)
        } else {
            AppLog.w("Core/$coreId", "Process did not exit after destroy() on Android API < 26")
        }
    }

    fun isRunning(): Boolean = process?.isAliveCompat() == true

    fun warpConfig(): File = File(runtimeDir, "config.json")

    private fun appendOutput(line: String) {
        if (line.isBlank()) return
        synchronized(outputTail) {
            outputTail.addLast(line.take(900))
            while (outputTail.size > 18) outputTail.removeFirst()
        }
        AppLog.i("Core/$coreId", line.take(900))
    }

    private fun recentOutput(): String = synchronized(outputTail) {
        outputTail.joinToString("\n").takeLast(1800)
    }

    suspend fun registerWarpIfNeeded(accepted: Boolean) = withContext(Dispatchers.IO) {
        if (coreId != "warp" || warpConfig().isFile) return@withContext
        require(accepted) { "Cloudflare WARP terms must be accepted before registration." }
        val binary = executable()
        require(isBundled()) { "Bundled Usque core is missing from the installed APK." }
        val command = listOf(
            binary.absolutePath,
            "--config", warpConfig().absolutePath,
            "register", "--accept-tos", "--name", "dicodePing-Android",
        )
        val registration = ProcessBuilder(command)
            .directory(runtimeDir)
            .redirectErrorStream(true)
            .start()
        val output = StringBuilder()
        val outputReader = thread(name = "dicodePing-warp-register-log", isDaemon = true) {
            runCatching {
                registration.inputStream.bufferedReader().forEachLine { line ->
                    synchronized(output) { output.appendLine(line) }
                    appendOutput(line)
                }
            }
        }
        if (!registration.waitForCompat(75_000L)) {
            registration.stopCompat()
            error("WARP registration timed out.")
        }
        outputReader.join(1_000L)
        val registrationOutput = synchronized(output) { output.toString() }
        check(registration.exitValue() == 0 && warpConfig().isFile) {
            registrationOutput.takeLast(1600).ifBlank { "WARP registration failed." }
        }
        AppLog.i("Core", "WARP registration completed")
    }

    suspend fun start(warpTermsAccepted: Boolean = false) = withContext(Dispatchers.IO) {
        stop()
        synchronized(outputTail) { outputTail.clear() }
        val binary = executable()
        require(isBundled()) {
            "Bundled $coreId core is missing from nativeLibraryDir for this device ABI."
        }
        if (coreId == "warp") registerWarpIfNeeded(warpTermsAccepted)

        val command = if (coreId == "aether") {
            listOf(
                binary.absolutePath,
                "--bind", "127.0.0.1:$socksPort",
                "--masque", "--balanced", "--quick-reconnect",
                "--noize", "firewall", "--log-level", "info",
            )
        } else {
            listOf(
                binary.absolutePath,
                "--config", warpConfig().absolutePath,
                "socks", "-b", "127.0.0.1", "-p", socksPort.toString(),
            )
        }

        process = ProcessBuilder(command)
            .directory(runtimeDir)
            .redirectErrorStream(true)
            .start()
            .also { child ->
                thread(name = "dicodePing-$coreId-log", isDaemon = true) {
                    runCatching {
                        child.inputStream.bufferedReader().forEachLine(::appendOutput)
                    }
                }
            }

        repeat(120) {
            val child = process
            if (child?.isAliveCompat() != true) {
                error(
                    recentOutput().ifBlank {
                        "$coreId stopped during startup with exit code ${runCatching { child?.exitValue() }.getOrNull()}."
                    }
                )
            }
            if (portReady()) return@withContext
            delay(250)
        }
        stop()
        error(recentOutput().ifBlank { "$coreId local SOCKS port did not become ready." })
    }

    private fun portReady(): Boolean = runCatching {
        Socket().use { socket ->
            socket.connect(InetSocketAddress("127.0.0.1", socksPort), 250)
        }
        true
    }.getOrDefault(false)

    @Synchronized
    fun stop() {
        val child = process ?: return
        process = null
        child.stopCompat()
    }
}
