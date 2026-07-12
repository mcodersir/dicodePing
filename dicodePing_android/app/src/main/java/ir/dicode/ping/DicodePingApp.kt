package ir.dicode.ping

import androidx.appcompat.app.AppCompatDelegate
import androidx.multidex.MultiDexApplication
import ir.dicode.ping.data.SettingsStore
import ir.dicode.ping.util.AppLog

class DicodePingApp : MultiDexApplication() {
    override fun onCreate() {
        super.onCreate()
        AppLog.init(this)
        val previousHandler = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, error ->
            AppLog.e("Crash", "Unhandled exception on ${thread.name}", error)
            previousHandler?.uncaughtException(thread, error)
        }

        val theme = SettingsStore(this).theme
        AppCompatDelegate.setDefaultNightMode(
            when (theme) {
                "light" -> AppCompatDelegate.MODE_NIGHT_NO
                "dark" -> AppCompatDelegate.MODE_NIGHT_YES
                else -> AppCompatDelegate.MODE_NIGHT_FOLLOW_SYSTEM
            }
        )
    }
}
