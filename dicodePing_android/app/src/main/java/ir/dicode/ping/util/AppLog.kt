package ir.dicode.ping.util

import android.content.Context
import android.util.Log
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

object AppLog {
    private const val MAX_BYTES = 1_500_000L
    private const val TAG_ROOT = "dicodePing"
    private val lock = Any()
    @Volatile private var appContext: Context? = null
    @Volatile private var enabled = false
    private val formatter = SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.US)

    fun init(context: Context) {
        appContext = context.applicationContext
        enabled = context.getSharedPreferences("dicodeping", Context.MODE_PRIVATE)
            .getBoolean("diagnostic_logging", false)
        i("App", "Diagnostic logging initialized")
    }

    fun setEnabled(context: Context, value: Boolean) {
        appContext = context.applicationContext
        enabled = value
        if (!value) clear(context)
        else i("App", "Diagnostic logging enabled")
    }

    fun i(tag: String, message: String) {
        if (!enabled) return
        Log.i("$TAG_ROOT/$tag", message)
        write("INFO", tag, message, null)
    }

    fun w(tag: String, message: String, error: Throwable? = null) {
        if (!enabled) return
        Log.w("$TAG_ROOT/$tag", message, error)
        write("WARN", tag, message, error)
    }

    fun e(tag: String, message: String, error: Throwable? = null) {
        if (!enabled) return
        Log.e("$TAG_ROOT/$tag", message, error)
        write("ERROR", tag, message, error)
    }

    fun logFile(context: Context? = appContext): File? =
        context?.let { File(it.filesDir, "logs/dicodePing.log") }

    fun exportSnapshot(context: Context): File {
        synchronized(lock) {
            val source = logFile(context)
            val dir = File(context.cacheDir, "shared_logs").apply { mkdirs() }
            val target = File(dir, "dicodePing-diagnostic.log")
            if (source?.exists() == true) source.copyTo(target, overwrite = true)
            else target.writeText("No diagnostic entries have been recorded yet.\n")
            return target
        }
    }

    fun clear(context: Context) {
        synchronized(lock) {
            logFile(context)?.delete()
        }
    }

    private fun write(level: String, tag: String, message: String, error: Throwable?) {
        val context = appContext ?: return
        synchronized(lock) {
            runCatching {
                val file = logFile(context) ?: return
                file.parentFile?.mkdirs()
                if (file.length() > MAX_BYTES) {
                    val previous = File(file.parentFile, "dicodePing.previous.log")
                    previous.delete()
                    file.renameTo(previous)
                }
                val stamp = formatter.format(Date())
                val detail = error?.stackTraceToString()?.let { "\n$it" }.orEmpty()
                file.appendText("$stamp | $level | $tag | $message$detail\n", Charsets.UTF_8)
            }
        }
    }
}
