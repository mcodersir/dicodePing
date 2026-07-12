package ir.dicode.ping.util

import android.content.Context
import android.content.res.Configuration
import java.util.Locale

object LocaleHelper {
    fun wrap(context: Context, language: String): Context {
        if (language == "system") return context
        val locale = Locale(language)
        Locale.setDefault(locale)
        val config = Configuration(context.resources.configuration)
        config.setLocale(locale)
        config.setLayoutDirection(locale)
        return context.createConfigurationContext(config)
    }
}
