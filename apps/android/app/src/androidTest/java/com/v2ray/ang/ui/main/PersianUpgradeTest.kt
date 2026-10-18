package com.v2ray.ang.ui.main

import android.app.LocaleManager
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import com.v2ray.ang.AppConfig
import com.v2ray.ang.handler.AppLocaleManager
import com.v2ray.ang.handler.MmkvManager
import org.junit.Assert.assertEquals
import org.junit.Test

class PersianUpgradeTest {
    @Test fun upgradeUsesPersianOnceThenHonoursTheLanguagePicker() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        if (android.os.Build.VERSION.SDK_INT < 33) return
        val locales = context.getSystemService(LocaleManager::class.java)
        MmkvManager.encodeSettings(AppConfig.PREF_DICODE_AUTO_TEST, false)
        MmkvManager.encodeSettings(AppConfig.PREF_TELEGRAM_PROMPT_COUNT, 3)
        ActivityScenario.launch(MainActivity::class.java).use {
        instrumentation.runOnMainSync {
            MmkvManager.encodeSettings("dicode_persian_default_493", false)
            MmkvManager.encodeSettings(AppConfig.PREF_LANGUAGE, "en")
            AppLocaleManager.initialize(context)
            assertEquals("fa", locales.applicationLocales[0].language)
            AppLocaleManager.setApplicationLanguage("en")
            AppLocaleManager.initialize(context)
            assertEquals("en", locales.applicationLocales[0].language)
            AppLocaleManager.setApplicationLanguage("fa")
        }
        }
    }
}
