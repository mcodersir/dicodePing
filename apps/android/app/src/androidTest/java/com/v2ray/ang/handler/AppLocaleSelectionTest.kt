package com.v2ray.ang.handler

import androidx.test.platform.app.InstrumentationRegistry
import com.v2ray.ang.AppConfig
import org.junit.Assert.assertEquals
import org.junit.Test

class AppLocaleSelectionTest {
    @Test fun explicitChineseAndSystemChoicesAreNotReplacedWithPersian() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val previous = MmkvManager.decodeSettingsString(AppConfig.PREF_LANGUAGE) ?: "auto"
        instrumentation.runOnMainSync {
            try {
                for (code in listOf("en", "zh-rCN", "zh-rTW", "auto", "fa", "ar")) {
                    AppLocaleManager.setApplicationLanguage(code)
                    assertEquals(code, MmkvManager.decodeSettingsString(AppConfig.PREF_LANGUAGE))
                }
            } finally {
                AppLocaleManager.setApplicationLanguage(previous)
            }
        }
    }
}
