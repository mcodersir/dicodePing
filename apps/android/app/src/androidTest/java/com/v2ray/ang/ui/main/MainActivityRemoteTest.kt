package com.v2ray.ang.ui.main

import android.view.KeyEvent
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.test.core.app.ActivityScenario
import androidx.test.espresso.Espresso
import androidx.test.platform.app.InstrumentationRegistry
import com.v2ray.ang.AppConfig
import com.v2ray.ang.R
import com.v2ray.ang.dto.entities.ProfileItem
import com.v2ray.ang.enums.EConfigType
import com.v2ray.ang.handler.MmkvManager
import org.junit.Rule
import org.junit.Test
import org.junit.Assert.assertEquals

/** Exercises the actual main screen's merged focus semantics and drawer using remote keys. */
class MainActivityRemoteTest {
    @get:Rule val compose = createEmptyComposeRule()
    @Test fun mainScreenRowsConnectionControlAndDrawerAreReachable() {
        // Exercise the app's remote navigation after first-run Android notification consent.
        // The OS dialog owns a separate window and is outside this screen's focus traversal.
        if (android.os.Build.VERSION.SDK_INT >= 33) {
            val instrumentation = InstrumentationRegistry.getInstrumentation()
            instrumentation.uiAutomation.grantRuntimePermission(
                instrumentation.targetContext.packageName, android.Manifest.permission.POST_NOTIFICATIONS
            )
        }
        MmkvManager.encodeSettings(AppConfig.PREF_DICODE_AUTO_TEST, false)
        MmkvManager.encodeSettings(AppConfig.PREF_TELEGRAM_PROMPT_COUNT, 3)
        MmkvManager.encodeSettings(AppConfig.CACHE_SUBSCRIPTION_ID, "")
        val first = MmkvManager.encodeServerConfig("", ProfileItem.create(EConfigType.VLESS).apply { remarks = "Remote test server one"; server = "127.0.0.1"; serverPort = "443"; security = "tls" })
        val second = MmkvManager.encodeServerConfig("", ProfileItem.create(EConfigType.VLESS).apply { remarks = "Remote test server two"; server = "127.0.0.1"; serverPort = "443"; security = "tls" })
        try {
            ActivityScenario.launch(MainActivity::class.java).use { scenario ->
                var menu = ""; var settings = ""; var connect = ""
                scenario.onActivity { menu = it.getString(R.string.acc_open_menu); settings = it.getString(R.string.title_server_pool); connect = it.getString(R.string.fab_manual_connect) }
                compose.waitUntil(15_000) { compose.onAllNodesWithText("Remote test server one").fetchSemanticsNodes().isNotEmpty() }
                remoteKey(KeyEvent.KEYCODE_DPAD_DOWN)
                compose.onNodeWithText("Remote test server one").performSemanticsAction(SemanticsActions.RequestFocus)
                compose.onNodeWithText("Remote test server one").assertIsFocused()
                remoteKey(KeyEvent.KEYCODE_DPAD_CENTER)
                compose.waitUntil(3_000) { MmkvManager.getSelectServer() == first }
                // Traverse the actual list/grid, including its nested row buttons, with a remote.
                val oneBounds = compose.onNodeWithText("Remote test server one").fetchSemanticsNode().boundsInRoot
                val twoBounds = compose.onNodeWithText("Remote test server two").fetchSemanticsNode().boundsInRoot
                val nextKey = when {
                    twoBounds.top >= oneBounds.bottom -> KeyEvent.KEYCODE_DPAD_DOWN
                    twoBounds.left >= oneBounds.right -> KeyEvent.KEYCODE_DPAD_RIGHT
                    else -> KeyEvent.KEYCODE_DPAD_LEFT
                }
                remoteKey(nextKey)
                compose.onNodeWithText("Remote test server two").assertIsFocused()
                remoteKey(KeyEvent.KEYCODE_DPAD_CENTER)
                compose.waitUntil(3_000) { MmkvManager.getSelectServer() == second }
                compose.onNodeWithContentDescription(connect).performSemanticsAction(SemanticsActions.RequestFocus)
                compose.onNodeWithContentDescription(connect).assertIsFocused().assertHasClickAction()
                compose.onNodeWithContentDescription(menu).performSemanticsAction(SemanticsActions.RequestFocus)
                compose.onNodeWithContentDescription(menu).assertIsFocused()
                remoteKey(KeyEvent.KEYCODE_DPAD_CENTER)
                compose.onNodeWithText(settings).assertIsDisplayed()
                // BACK is dispatched by Android to OnBackPressedDispatcher, outside Compose key input.
                Espresso.pressBack()
                compose.onNodeWithText("Remote test server two").assertIsDisplayed()
                compose.onNodeWithContentDescription(menu).performSemanticsAction(SemanticsActions.RequestFocus)
                remoteKey(KeyEvent.KEYCODE_DPAD_CENTER)
                compose.onNodeWithText(settings).assertIsDisplayed()
                remoteKey(KeyEvent.KEYCODE_BUTTON_B)
                compose.onNodeWithText("Remote test server two").assertIsDisplayed()
                assertEquals(second, MmkvManager.getSelectServer())
            }
        } finally { MmkvManager.tryRemoveServer(first); MmkvManager.tryRemoveServer(second) }
    }
}
