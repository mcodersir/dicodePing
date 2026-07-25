package ir.dicode.ping.core

import android.content.Context
import android.content.Intent
import androidx.core.content.FileProvider
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request

/** Downloads optional cores outside the APK and verifies them before use. */
class AndroidCoreManager(private val context: Context) {
    private val root = File(context.filesDir, "cores").apply { mkdirs() }
    private val client = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(3, TimeUnit.MINUTES)
        .followRedirects(true)
        .build()

    data class Asset(val url: String, val sha256: String, val fileName: String)

    fun isInstalled(coreId: String): Boolean {
        if (coreId == "xray") return true
        val asset = assetFor(coreId)
        val file = File(File(root, coreId), asset.fileName)
        return file.isFile && sha256(file).equals(asset.sha256, ignoreCase = true)
    }

    suspend fun install(coreId: String, progress: (Long, Long) -> Unit = { _, _ -> }) =
        withContext(Dispatchers.IO) {
            require(coreId != "xray") { "Xray is built in" }
            val asset = assetFor(coreId)
            val directory = File(root, coreId).apply { mkdirs() }
            val target = File(directory, asset.fileName)
            val partial = File(directory, "${asset.fileName}.part")
            partial.delete()
            client.newCall(Request.Builder().url(asset.url).build()).execute().use { response ->
                check(response.isSuccessful) { "HTTP ${response.code}" }
                val body = response.body ?: error("Empty response")
                val total = body.contentLength()
                check(total in 1..MAX_DOWNLOAD_BYTES) { "Invalid download size: $total" }
                body.byteStream().use { input ->
                    partial.outputStream().buffered().use { output ->
                        val buffer = ByteArray(64 * 1024)
                        var received = 0L
                        while (true) {
                            val count = input.read(buffer)
                            if (count < 0) break
                            received += count
                            check(received <= MAX_DOWNLOAD_BYTES) { "Download exceeds safety limit" }
                            output.write(buffer, 0, count)
                            progress(received, total)
                        }
                    }
                }
            }
            val actual = sha256(partial)
            check(actual.equals(asset.sha256, ignoreCase = true)) {
                partial.delete()
                "SHA-256 mismatch"
            }
            if (target.exists()) target.delete()
            check(partial.renameTo(target)) { "Could not atomically install core" }
        }

    /**
     * Psiphon is a separately installed verified companion APK. Aether's
     * official Android build runs in Termux, also separately from this APK.
     */
    fun open(coreId: String): Boolean {
        if (coreId == "psiphon") {
            context.packageManager.getLaunchIntentForPackage(PSIPHON_PACKAGE)?.let {
                it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                context.startActivity(it)
                return true
            }
            val apk = File(File(root, coreId), assetFor(coreId).fileName)
            if (!apk.isFile || !isInstalled(coreId)) return false
            val uri = FileProvider.getUriForFile(context, "${context.packageName}.files", apk)
            context.startActivity(
                Intent(Intent.ACTION_VIEW)
                    .setDataAndType(uri, "application/vnd.android.package-archive")
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION)
            )
            return true
        }
        if (coreId == "aether" && isInstalled(coreId)) {
            context.packageManager.getLaunchIntentForPackage("com.termux")?.let {
                it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                context.startActivity(it)
                return true
            }
        }
        return false
    }

    private fun assetFor(coreId: String): Asset = when (coreId) {
        "psiphon" -> Asset(
            "https://github.com/shirokhorshid/shirokhorshid-android/releases/download/v2026.05.24-a3b91cf/ShirOKhorshid-2026.05.24.apk",
            "9d8c11c6450df689a7632fb02b73fd1a7c524ed26870e21a6c617f1981be4d79",
            "ShirOKhorshid-2026.05.24.apk",
        )
        "aether" -> when {
            android.os.Build.SUPPORTED_ABIS.any { it == "arm64-v8a" } -> Asset(
                "https://github.com/CluvexStudio/Aether/releases/download/v1.4.0/aether-android-arm64.tar.gz",
                "1a989fb9d811888632f71a66edb807e24da14589236b9492cd4189aa77829936",
                "aether-android-arm64.tar.gz",
            )
            android.os.Build.SUPPORTED_ABIS.any { it == "armeabi-v7a" } -> Asset(
                "https://github.com/CluvexStudio/Aether/releases/download/v1.4.0/aether-android-armv7.tar.gz",
                "1cba8942a87c14ff953ae85c728440bab6ece92441d609fd12b6fe39820a1789",
                "aether-android-armv7.tar.gz",
            )
            else -> Asset(
                "https://github.com/CluvexStudio/Aether/releases/download/v1.4.0/aether-android-x86_64.tar.gz",
                "72b8247e045aaead509f2936a8012bdcafd412b38094fdc99b608efc135d808a",
                "aether-android-x86_64.tar.gz",
            )
        }
        else -> error("Unknown core: $coreId")
    }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().buffered().use { input ->
            val buffer = ByteArray(64 * 1024)
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                digest.update(buffer, 0, count)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    companion object {
        private const val MAX_DOWNLOAD_BYTES = 300L * 1024 * 1024
        private const val PSIPHON_PACKAGE = "com.shirokhorshid.vpn"
    }
}
