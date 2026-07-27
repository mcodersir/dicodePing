package ir.dicode.ping.core

import android.content.Context
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

    fun isRunning(): Boolean = process?.isAlive == true

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
        val output = registration.inputStream.bufferedReader().use { it.readText() }
        if (!registration.waitFor(75, TimeUnit.SECONDS)) {
            registration.destroyForcibly()
            error("WARP registration timed out.")
        }
        check(registration.exitValue() == 0 && warpConfig().isFile) {
            output.takeLast(1600).ifBlank { "WARP registration failed." }
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
            if (child?.isAlive != true) {
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
        runCatching { child.destroy() }
        runCatching {
            if (!child.waitFor(2, TimeUnit.SECONDS)) {
                child.destroyForcibly()
                child.waitFor(2, TimeUnit.SECONDS)
            }
        }
    }
}
