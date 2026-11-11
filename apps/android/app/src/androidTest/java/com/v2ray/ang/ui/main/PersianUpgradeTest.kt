package com.v2ray.ang.ui.main

import android.app.LocaleManager
import android.os.LocaleList
import androidx.test.platform.app.InstrumentationRegistry
import com.v2ray.ang.AppConfig
import com.v2ray.ang.handler.AppLocaleManager
import com.v2ray.ang.handler.MmkvManager
import org.junit.Assert.assertEquals
import org.junit.Test

class PersianUpgradeTest {
    @Test fun upgradePreservesLanguageChoicesWithoutForcingPersian() {
        if (android.os.Build.VERSION.SDK_INT < 33) return
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val locales = context.getSystemService(LocaleManager::class.java)
        val previousLocales = locales.applicationLocales
        val previousLanguage = MmkvManager.decodeSettingsString(AppConfig.PREF_LANGUAGE) ?: "auto"
        val previousMigration = MmkvManager.decodeSettingsBool(AppConfig.PREF_APP_LOCALE_MIGRATED, false)
        val previousPersianRevision = MmkvManager.decodeSettingsBool("dicode_persian_default_493", false)
        instrumentation.runOnMainSync {
            try {
                // Simulate the first handoff from legacy preferences, before an
                // activity exists. 5.0.3 must preserve explicit English/Chinese,
                // and an empty system-language locale list, even if 4.9.3's old
                // Persian-default revision was never recorded.
                for ((code, tag) in listOf("en" to "en", "zh-rCN" to "zh-CN", "fa" to "fa", "auto" to "")) {
                    locales.applicationLocales = LocaleList.getEmptyLocaleList()
                    MmkvManager.encodeSettings(AppConfig.PREF_APP_LOCALE_MIGRATED, false)
                    MmkvManager.encodeSettings("dicode_persian_default_493", false)
                    MmkvManager.encodeSettings(AppConfig.PREF_LANGUAGE, code)
                    AppLocaleManager.initialize(context)
                    assertEquals(code, tag, locales.applicationLocales.toLanguageTags())
                    assertEquals(code, MmkvManager.decodeSettingsString(AppConfig.PREF_LANGUAGE))
                    AppLocaleManager.initialize(context)
                    assertEquals("Repeated initialization changed $code", tag, locales.applicationLocales.toLanguageTags())
                }
            } finally {
                locales.applicationLocales = previousLocales
                MmkvManager.encodeSettings(AppConfig.PREF_LANGUAGE, previousLanguage)
                MmkvManager.encodeSettings(AppConfig.PREF_APP_LOCALE_MIGRATED, previousMigration)
                MmkvManager.encodeSettings("dicode_persian_default_493", previousPersianRevision)
            }
        }
    }
}
