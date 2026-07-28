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
import kotlinx.coroutines.CancellationException
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
    private val onStage: (Stage) -> Unit = {},
) {
    enum class Stage {
        PREPARING,
        REGISTERING_WARP,
        STARTING_PRIMARY,
        STARTING_HTTP2_FALLBACK,
        WAITING_FOR_PROXY,
        PROXY_READY,
    }

    val socksPort: Int = when (coreId) {
        "aether" -> 1819
        "warp" -> 1820
        else -> error("Unsupported external core: $coreId")
    }

    private var process: Process? = null
    @Volatile private var proxyReadyAnnounced = false
    private val runtimeDir = File(context.filesDir, "core-state/$coreId").apply { mkdirs() }
    private val tempDir = File(runtimeDir, "tmp").apply { mkdirs() }
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

    /** API-24-safe timed wait. */
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
            while (outputTail.size > 30) outputTail.removeFirst()
        }
        val normalized = line.lowercase()
        // Registration has its own explicit stage. Only runtime output may move
        // the UI through proxy-startup stages, and never regress after ready.
        if (process?.isAliveCompat() == true) {
            if (normalized.contains("listening") || normalized.contains("socks5 proxy")) {
                proxyReadyAnnounced = true
                onStage(Stage.PROXY_READY)
            } else if (!proxyReadyAnnounced && (
                normalized.contains("scan") || normalized.contains("gateway") ||
                    normalized.contains("endpoint") || normalized.contains("connect")
            )) {
                onStage(Stage.WAITING_FOR_PROXY)
            }
        }
        AppLog.i("Core/$coreId", line.take(900))
    }

    private fun recentOutput(): String = synchronized(outputTail) {
        outputTail.joinToString("\n").takeLast(3000)
    }

    private fun processBuilder(command: List<String>): ProcessBuilder = ProcessBuilder(command)
        .directory(runtimeDir)
        .redirectErrorStream(true)
        .also { builder ->
            val env = builder.environment()
            env["HOME"] = runtimeDir.absolutePath
            env["TMPDIR"] = tempDir.absolutePath
            env["XDG_CONFIG_HOME"] = runtimeDir.absolutePath
            env["XDG_CACHE_HOME"] = File(runtimeDir, "cache").apply { mkdirs() }.absolutePath
            env["RUST_BACKTRACE"] = "1"
            val nativeDir = context.applicationInfo.nativeLibraryDir
            env["LD_LIBRARY_PATH"] = listOf(nativeDir, env["LD_LIBRARY_PATH"].orEmpty())
                .filter(String::isNotBlank)
                .joinToString(":")
        }

    suspend fun registerWarpIfNeeded(accepted: Boolean) = withContext(Dispatchers.IO) {
        if (coreId != "warp" || warpConfig().isFile) return@withContext
        onStage(Stage.REGISTERING_WARP)
        require(accepted) { "Cloudflare WARP terms must be accepted before registration." }
        val binary = executable()
        require(isBundled()) { "Bundled Usque core is missing from the installed APK." }
        val registration = processBuilder(
            ExternalCoreCommandBuilder.registration(binary.absolutePath, warpConfig().absolutePath)
        ).start()
        val output = StringBuilder()
        val outputReader = thread(name = "dicodePing-warp-register-log", isDaemon = true) {
            runCatching {
                registration.inputStream.bufferedReader().forEachLine { line ->
                    synchronized(output) { output.appendLine(line) }
                    appendOutput(line)
                }
            }
        }
        val registrationDeadline = SystemClock.elapsedRealtime() + WARP_REGISTRATION_TIMEOUT_MS
        try {
            while (registration.isAliveCompat() && SystemClock.elapsedRealtime() < registrationDeadline) {
                delay(250L)
            }
            if (registration.isAliveCompat()) {
                registration.stopCompat()
                error("WARP registration timed out.")
            }
        } catch (cancelled: CancellationException) {
            registration.stopCompat()
            throw cancelled
        }
        outputReader.join(1_000L)
        val registrationOutput = synchronized(output) { output.toString() }
        check(registration.exitValue() == 0 && warpConfig().isFile && warpConfig().length() > 64L) {
            registrationOutput.takeLast(2400).ifBlank { "WARP registration failed." }
        }
        AppLog.i("Core", "WARP registration completed")
    }

    suspend fun start(
        warpTermsAccepted: Boolean = false,
        http2Fallback: Boolean = false,
    ) = withContext(Dispatchers.IO) {
        stop()
        synchronized(outputTail) { outputTail.clear() }
        proxyReadyAnnounced = false
        onStage(Stage.PREPARING)
        val binary = executable()
        require(isBundled()) {
            "Bundled $coreId core is missing from nativeLibraryDir for this device ABI."
        }
        if (coreId == "warp") registerWarpIfNeeded(warpTermsAccepted)

        onStage(if (http2Fallback) Stage.STARTING_HTTP2_FALLBACK else Stage.STARTING_PRIMARY)
        val command = ExternalCoreCommandBuilder.runtime(
            coreId = coreId,
            binary = binary.absolutePath,
            config = warpConfig().absolutePath,
            socksPort = socksPort,
            http2Fallback = http2Fallback,
        )
        AppLog.i("Core/$coreId", "Starting bundled core; transport=${if (http2Fallback) "http2" else "primary"}")
        val child = processBuilder(command).start()
        process = child
        thread(name = "dicodePing-$coreId-log", isDaemon = true) {
            runCatching {
                child.inputStream.bufferedReader().forEachLine(::appendOutput)
            }
        }

        onStage(Stage.WAITING_FOR_PROXY)
        val timeoutMs = if (coreId == "aether") AETHER_START_TIMEOUT_MS else WARP_START_TIMEOUT_MS
        val deadline = SystemClock.elapsedRealtime() + timeoutMs
        while (SystemClock.elapsedRealtime() < deadline) {
            val child = process
            if (child?.isAliveCompat() != true) {
                error(
                    recentOutput().ifBlank {
                        "$coreId stopped during startup with exit code ${runCatching { child?.exitValue() }.getOrNull()}."
                    }
                )
            }
            if (portReady()) {
                proxyReadyAnnounced = true
                onStage(Stage.PROXY_READY)
                return@withContext
            }
            delay(300L)
        }
        stop()
        error(recentOutput().ifBlank { "$coreId local SOCKS port did not become ready before timeout." })
    }

    private fun portReady(): Boolean = runCatching {
        Socket().use { socket ->
            socket.connect(InetSocketAddress("127.0.0.1", socksPort), 350)
        }
        true
    }.getOrDefault(false)

    @Synchronized
    fun stop() {
        val child = process ?: return
        process = null
        child.stopCompat()
    }

    private companion object {
        const val WARP_REGISTRATION_TIMEOUT_MS = 120_000L
        const val AETHER_START_TIMEOUT_MS = 180_000L
        const val WARP_START_TIMEOUT_MS = 45_000L
    }
}
