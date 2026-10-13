package com.v2ray.ang.handler

import androidx.appcompat.app.AppCompatDelegate
import java.util.Locale

/** Use the application's locale, including workers and log producers. */
internal object PoolStrings {
    fun t(fa: String, en: String): String {
        val language = runCatching { AppCompatDelegate.getApplicationLocales()[0]?.language }.getOrNull() ?: Locale.getDefault().language
        return if (language == "fa") fa else en
    }
    fun stage(value: String): String = when (value) {
        "آماده" -> t(value, "Ready")
        "شروع" -> t(value, "Starting")
        "مسیر فعال" -> t(value, "Active route")
        "استخر" -> t(value, "Server pool")
        "ساب پیش‌فرض" -> t(value, "Default subscription")
        "اتصال" -> t(value, "Connecting")
        "کانال‌ها" -> t(value, "Channels")
        "جمع‌آوری" -> t(value, "Collecting")
        "آزمون" -> t(value, "Testing")
        "ذخیره" -> t(value, "Saving")
        "توقف" -> t(value, "Stopping")
        "متوقف" -> t(value, "Stopped")
        "پایان" -> t(value, "Finished")
        "خطا" -> t(value, "Error")
        else -> value
    }
}
