package com.v2ray.ang.core

import android.content.Context
import com.v2ray.ang.AppConfig
import com.v2ray.ang.util.LogUtil
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.net.InetSocketAddress
import java.net.Proxy
import java.net.Socket
import java.util.UUID
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

/** Owned subprocess, private files, bounded startup, and explicit cleanup. */
internal class SingBoxProcess(private val context: Context) : AutoCloseable {
    private var process: Process? = null
    private val directory = File(context.cacheDir, "sing-box-${UUID.randomUUID()}")
    @Volatile private var stopped = false

    fun start(content: String, port: Int, onExit: (() -> Unit)? = null) {
        val executable = File(context.applicationInfo.nativeLibraryDir, "libsingbox.so")
        check(executable.isFile && executable.canExecute()) { "sing-box binary unavailable on this architecture" }
        directory.mkdirs()
        val config = File(directory, "config.json").apply { writeText(SingBoxConfig.prepare(content, port)) }
        val command = ProcessBuilder(executable.absolutePath, "run", "-c", config.absolutePath)
            .directory(directory).redirectErrorStream(true)
        listOf("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy").forEach { command.environment().remove(it) }
        command.environment()["TMPDIR"] = context.cacheDir.absolutePath
        val started = command.start(); process = started
        thread(name = "DicodeSingBoxLog", isDaemon = true) {
            runCatching { started.inputStream.bufferedReader().useLines { lines -> lines.forEach { LogUtil.i(AppConfig.TAG, "sing-box: $it") } } }
            runCatching { started.waitFor() }
            if (!stopped) onExit?.invoke()
        }
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10)
        while (System.nanoTime() < deadline && started.isAlive) {
            try { Socket().use { it.connect(InetSocketAddress("127.0.0.1", port), 150) }; return }
            catch (_: Exception) { Thread.sleep(50) }
        }
        close(); error("sing-box did not open its local proxy")
    }

    fun measure(port: Int, url: String): Long {
        val client = OkHttpClient.Builder().proxy(Proxy(Proxy.Type.SOCKS, InetSocketAddress("127.0.0.1", port)))
            .callTimeout(20, TimeUnit.SECONDS).connectTimeout(10, TimeUnit.SECONDS).build()
        try {
            val start = System.nanoTime()
            client.newCall(Request.Builder().url(url).build()).execute().use { response ->
                if (response.code !in 200..399) return -1
                return ((System.nanoTime() - start) / 1_000_000).coerceAtLeast(1)
            }
        } finally { client.dispatcher.cancelAll(); client.connectionPool.evictAll(); client.dispatcher.executorService.shutdown() }
    }
    override fun close() {
        stopped = true
        process?.let { p -> p.destroy(); if (!p.waitFor(2, TimeUnit.SECONDS)) { p.destroyForcibly(); p.waitFor(2, TimeUnit.SECONDS) } }
        process = null; directory.deleteRecursively()
    }
}
