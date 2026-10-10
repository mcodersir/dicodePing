package com.v2ray.ang.ui.main

import android.view.KeyEvent
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.test.core.app.ActivityScenario
import androidx.test.espresso.Espresso
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
        MmkvManager.encodeSettings(AppConfig.PREF_DICODE_AUTO_TEST, false)
        MmkvManager.encodeSettings(AppConfig.CACHE_SUBSCRIPTION_ID, "")
        val first = MmkvManager.encodeServerConfig("", ProfileItem.create(EConfigType.VLESS).apply { remarks = "Remote test server one"; server = "127.0.0.1"; serverPort = "443"; security = "tls" })
        val second = MmkvManager.encodeServerConfig("", ProfileItem.create(EConfigType.VLESS).apply { remarks = "Remote test server two"; server = "127.0.0.1"; serverPort = "443"; security = "tls" })
        try {
            ActivityScenario.launch(MainActivity::class.java).use { scenario ->
                var menu = ""; var settings = ""; var connect = ""
                scenario.onActivity { menu = it.getString(R.string.acc_open_menu); settings = it.getString(R.string.title_server_pool); connect = it.getString(R.string.fab_manual_connect) }
                compose.waitUntil(15_000) { compose.onAllNodesWithText("Remote test server one").fetchSemanticsNodes().isNotEmpty() }
                Espresso.pressKey(KeyEvent.KEYCODE_DPAD_DOWN)
                compose.onNodeWithText("Remote test server one").performSemanticsAction(SemanticsActions.RequestFocus)
                compose.onNodeWithText("Remote test server one").assertIsFocused()
                Espresso.pressKey(KeyEvent.KEYCODE_DPAD_CENTER)
                compose.waitUntil(3_000) { MmkvManager.getSelectServer() == first }
                // Traverse the actual list/grid, including its nested row buttons, with a remote.
                val oneBounds = compose.onNodeWithText("Remote test server one").fetchSemanticsNode().boundsInRoot
                val twoBounds = compose.onNodeWithText("Remote test server two").fetchSemanticsNode().boundsInRoot
                val nextKey = when {
                    twoBounds.top >= oneBounds.bottom -> KeyEvent.KEYCODE_DPAD_DOWN
                    twoBounds.left >= oneBounds.right -> KeyEvent.KEYCODE_DPAD_RIGHT
                    else -> KeyEvent.KEYCODE_DPAD_LEFT
                }
                Espresso.pressKey(nextKey)
                compose.onNodeWithText("Remote test server two").assertIsFocused()
                Espresso.pressKey(KeyEvent.KEYCODE_DPAD_CENTER)
                compose.waitUntil(3_000) { MmkvManager.getSelectServer() == second }
                compose.onNodeWithContentDescription(connect).performSemanticsAction(SemanticsActions.RequestFocus)
                compose.onNodeWithContentDescription(connect).assertIsFocused().assertHasClickAction()
                compose.onNodeWithContentDescription(menu).performSemanticsAction(SemanticsActions.RequestFocus)
                compose.onNodeWithContentDescription(menu).assertIsFocused()
                Espresso.pressKey(KeyEvent.KEYCODE_DPAD_CENTER)
                compose.onNodeWithText(settings).assertIsDisplayed()
                // BACK is dispatched by Android to OnBackPressedDispatcher, outside Compose key input.
                Espresso.pressBack()
                compose.onNodeWithText("Remote test server two").assertIsDisplayed()
                assertEquals(second, MmkvManager.getSelectServer())
            }
        } finally { MmkvManager.tryRemoveServer(first); MmkvManager.tryRemoveServer(second) }
    }
}
