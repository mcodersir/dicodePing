package com.v2ray.ang.ui.main

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.ui.Modifier
import android.view.KeyEvent
import androidx.test.platform.app.InstrumentationRegistry
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import org.junit.Rule
import org.junit.Test
import org.junit.Assert.assertEquals

/** Native key injection also switches Android out of touch mode, as a physical remote does. */
internal fun remoteKey(keyCode: Int) = InstrumentationRegistry.getInstrumentation().sendKeyDownUpSync(keyCode)

class RemoteNavigationTest {
    @get:Rule val compose = createComposeRule()

    @Test fun dpadTraversesServerRowsAndActivatesConnectionAndMenu() {
        var selected = 0
        var connects = 0
        var menus = 0
        compose.setContent {
            MaterialTheme {
                Column {
                    for (i in 1..2) Text("Server $i", Modifier.fillMaxWidth().remoteFocus().testTag("server$i").clickable { selected = i })
                    Button(onClick = { connects++ }, modifier = Modifier.remoteFocus().testTag("connect")) { Text("Connect") }
                    Button(onClick = { menus++ }, modifier = Modifier.remoteFocus().testTag("menu")) { Text("Menu") }
                }
            }
        }
        remoteKey(KeyEvent.KEYCODE_DPAD_DOWN)
        compose.onNodeWithTag("server1").performSemanticsAction(SemanticsActions.RequestFocus)
        compose.onNodeWithTag("server1").assertIsFocused()
        remoteKey(KeyEvent.KEYCODE_DPAD_CENTER)
        compose.runOnIdle { assertEquals(1, selected) }
        remoteKey(KeyEvent.KEYCODE_DPAD_DOWN)
        compose.onNodeWithTag("server2").assertIsFocused()
        remoteKey(KeyEvent.KEYCODE_DPAD_CENTER)
        compose.runOnIdle { assertEquals(2, selected) }
        remoteKey(KeyEvent.KEYCODE_DPAD_DOWN)
        compose.onNodeWithTag("connect").assertIsFocused()
        remoteKey(KeyEvent.KEYCODE_DPAD_CENTER)
        compose.runOnIdle { assertEquals(1, connects) }
        remoteKey(KeyEvent.KEYCODE_DPAD_DOWN)
        compose.onNodeWithTag("menu").assertIsFocused()
        remoteKey(KeyEvent.KEYCODE_DPAD_CENTER)
        compose.runOnIdle { assertEquals(1, menus) }
        remoteKey(KeyEvent.KEYCODE_DPAD_UP)
        compose.onNodeWithTag("connect").assertIsFocused()
    }
}
