package com.v2ray.ang.util

import android.content.Context
import android.os.Build
import com.v2ray.ang.BuildConfig
import java.io.File
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/** App-private, bounded diagnostics. Never includes account vaults or configuration files. */
object DiagnosticArchive {
    @Volatile private var directory: File? = null
    private val lock = Any()
    fun initialize(context: Context) {
        directory = File(context.filesDir, "diagnostics").apply { mkdirs() }
        val previous = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, error ->
            append("FATAL ${thread.name}: ${error.stackTraceToString()}")
            previous?.uncaughtException(thread, error)
        }
    }
    fun redact(text: String): String = text
        .replace(Regex("(?i)(Bearer\\s+)[^\\s\"']+"), "$1[redacted]")
        .replace(Regex("(?i)(\"?(?:access_token|refresh_token|session_token|password|token|authorization|private_key|privateKey|secret)\"?\\s*[:=]\\s*\"?)[^\"\\s,}]+"), "$1[redacted]")
        .replace(Regex("[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}"), "[email]")
        .replace(Regex("(?i)(?:vless|vmess|trojan|ss|socks5?)://[^\\s\"']+"), "[profile link]")
        .replace(Regex("(?i)\\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\\b"), "[id]")
    fun append(message: String) {
        val dir = directory ?: return
        runCatching { synchronized(lock) {
            val file = File(dir, "application.log")
            if (file.length() > 1024 * 1024) {
                File(dir, "previous.log").delete()
                file.renameTo(File(dir, "previous.log"))
            }
            file.appendText("${java.time.Instant.now()} ${redact(message).take(16384)}\n")
        } }
    }
    fun create(context: Context, logs: String): File {
        val dir = File(context.cacheDir, "shared_logs").apply { mkdirs() }
        dir.listFiles()?.filter { System.currentTimeMillis() - it.lastModified() > 86400000 }?.forEach { it.delete() }
        val file = File(dir, "DicodePing-diagnostics-${System.currentTimeMillis()}.zip")
        ZipOutputStream(file.outputStream()).use { zip ->
            fun entry(name: String, content: String) { zip.putNextEntry(ZipEntry(name)); zip.write(redact(content).toByteArray()); zip.closeEntry() }
            entry("device.txt", "version=${BuildConfig.VERSION_NAME}\ncode=${BuildConfig.VERSION_CODE}\nmanufacturer=${Build.MANUFACTURER}\nmodel=${Build.MODEL}\nandroid=${Build.VERSION.RELEASE}\nsdk=${Build.VERSION.SDK_INT}\nabis=${Build.SUPPORTED_ABIS.joinToString()}\ncores=${runCatching { com.v2ray.ang.core.CoreNativeManager.getLibVersion() }.getOrDefault("unavailable")}\n")
            entry("logcat.txt", logs.takeLast(2 * 1024 * 1024))
            synchronized(lock) { directory?.listFiles()?.filter { it.extension == "log" }?.forEach { entry(it.name, it.readText().takeLast(1024 * 1024)) } }
            entry("README.txt", "App diagnostics only. Account vaults, subscriptions and raw proxy configurations are excluded. Review the archive before sharing.")
        }
        return file
    }
}
