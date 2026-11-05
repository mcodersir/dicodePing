package com.v2ray.ang.ui.main

import android.view.KeyEvent
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import com.v2ray.ang.AppConfig
import com.v2ray.ang.BuildConfig
import com.v2ray.ang.R
import com.v2ray.ang.dto.entities.ProfileItem
import com.v2ray.ang.dto.entities.SubscriptionItem
import com.v2ray.ang.enums.EConfigType
import com.v2ray.ang.handler.MmkvManager
import com.v2ray.ang.util.Utils
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class TvMainRemoteTest {
    @get:Rule val compose = createEmptyComposeRule()

    @Test fun remoteSelectsProfilesAndOpensSettings() {
        assertTrue("TV test must run against the TV edition", BuildConfig.TV_EDITION)
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        if (android.os.Build.VERSION.SDK_INT >= 33) instrumentation.uiAutomation.grantRuntimePermission(
            instrumentation.targetContext.packageName, android.Manifest.permission.POST_NOTIFICATIONS,
        )
        MmkvManager.encodeSettings(AppConfig.PREF_DICODE_AUTO_TEST, false)
        val previousGroup = MmkvManager.decodeSettingsString(AppConfig.CACHE_SUBSCRIPTION_ID, "").orEmpty()
        val previousProfile = MmkvManager.getSelectServer()
        val group = Utils.getUuid()
        MmkvManager.encodeSubscription(group, SubscriptionItem(remarks = "TV fixture", enabled = false, autoUpdate = false))
        MmkvManager.encodeSettings(AppConfig.CACHE_SUBSCRIPTION_ID, group)
        fun profile(name: String) = MmkvManager.encodeServerConfig("", ProfileItem.create(EConfigType.VLESS).apply {
            subscriptionId = group; remarks = name; server = "127.0.0.1"; serverPort = "443"; security = "tls"
        })
        val first = profile("TV profile one")
        val second = profile("TV profile two")
        try {
            ActivityScenario.launch(MainActivity::class.java).use { scenario ->
                var settings = ""
                var connect = ""
                scenario.onActivity { settings = it.getString(R.string.title_settings); connect = it.getString(R.string.tv_connect) }
                compose.waitUntil(15_000) { compose.onAllNodesWithText("TV profile one").fetchSemanticsNodes(atLeastOneRootRequired = false).isNotEmpty() }
                compose.onNodeWithText(connect).assertIsFocused().assertHasClickAction()
                compose.onNodeWithText("TV profile one").performSemanticsAction(SemanticsActions.RequestFocus)
                remoteKey(KeyEvent.KEYCODE_DPAD_CENTER)
                compose.waitUntil(3_000) { MmkvManager.getSelectServer() == first }
                // Profiles can be ordered newest-first. Follow the actual
                // screen geometry instead of assuming their insertion order.
                val one = compose.onNodeWithText("TV profile one").fetchSemanticsNode().boundsInRoot
                val two = compose.onNodeWithText("TV profile two").fetchSemanticsNode().boundsInRoot
                remoteKey(if (two.top < one.top) KeyEvent.KEYCODE_DPAD_UP else KeyEvent.KEYCODE_DPAD_DOWN)
                compose.onNodeWithText("TV profile two").assertIsFocused()
                remoteKey(KeyEvent.KEYCODE_DPAD_CENTER)
                compose.waitUntil(3_000) { MmkvManager.getSelectServer() == second }
                // Instrumentation cleanup uninstalls the app, so keep the
                // screenshot outside its private directory until CI pulls it.
                compose.waitForIdle()
                android.os.ParcelFileDescriptor.AutoCloseInputStream(
                    instrumentation.uiAutomation.executeShellCommand("mkdir -p /sdcard/Download && screencap -p /sdcard/Download/dicode-tv-preview.png")
                ).use { it.readBytes() }
                compose.onNodeWithText(settings).performSemanticsAction(SemanticsActions.RequestFocus)
                remoteKey(KeyEvent.KEYCODE_DPAD_CENTER)
                compose.waitUntil(5_000) { compose.onAllNodesWithText("DicodePing TV").fetchSemanticsNodes(atLeastOneRootRequired = false).isEmpty() }
            }
        } finally {
            MmkvManager.removeSubscription(group)
            MmkvManager.encodeSettings(AppConfig.CACHE_SUBSCRIPTION_ID, previousGroup)
            if (previousProfile != null) MmkvManager.setSelectServer(previousProfile)
        }
    }
}
