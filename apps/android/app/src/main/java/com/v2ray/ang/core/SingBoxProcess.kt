package com.v2ray.ang.core

import android.content.Context
import com.v2ray.ang.util.DiagnosticArchive
import java.io.File
import java.net.InetSocketAddress
import java.net.Socket
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

/** One independent engine per session/probe; Xray continues to own Android's VPN interface. */
internal class SingBoxProcess(private val context: Context) : AutoCloseable {
    @Volatile private var process: Process? = null
    @Volatile private var stopped = false
    private var configFile: File? = null
    val isAlive: Boolean get() = process?.isAlive == true
    fun start(config: String, port: Int, onExit: (() -> Unit)? = null) {
        check(!stopped) { "sing-box start cancelled" }
        val binary = File(context.applicationInfo.nativeLibraryDir, "libsingbox.so")
        check(binary.isFile && binary.canExecute()) { "sing-box is missing; install the complete APK" }
        val file = File.createTempFile("singbox-", ".json", context.cacheDir)
        configFile = file
        file.setReadable(false, false); file.setWritable(false, false)
        file.setReadable(true, true); file.setWritable(true, true)
        file.writeText(config)
        val command = ProcessBuilder(binary.absolutePath, "run", "-c", file.absolutePath).directory(context.cacheDir).redirectErrorStream(true)
        listOf("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy").forEach { command.environment().remove(it) }
        val child = command.start(); process = child
        thread(isDaemon = true, name = "SingBoxOutput") {
            runCatching { child.inputStream.bufferedReader().useLines { lines -> lines.forEach { DiagnosticArchive.append("sing-box: ${it.take(2048)}") } } }
            runCatching { child.waitFor() }
            if (!stopped) onExit?.invoke()
        }
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(15)
        while (!stopped && child.isAlive && System.nanoTime() < deadline) {
            if (runCatching { Socket().use { socket ->
                socket.connect(InetSocketAddress("127.0.0.1", port), 200); socket.soTimeout = 200
                socket.getOutputStream().write(byteArrayOf(5, 1, 0)); socket.getOutputStream().flush()
                check(socket.getInputStream().read() == 5 && socket.getInputStream().read() == 0)
            } }.isSuccess) return
            Thread.sleep(50)
        }
        close()
        error("sing-box did not start; see Reports")
    }
    fun cancel() { stopped = true; process?.destroy() }
    override fun close() {
        stopped = true
        process?.let { child ->
            child.destroy()
            if (!child.waitFor(2, TimeUnit.SECONDS)) { child.destroyForcibly(); child.waitFor(2, TimeUnit.SECONDS) }
        }
        process = null
        configFile?.delete(); configFile = null
    }
}
