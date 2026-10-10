package com.v2ray.ang.ui.main

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.ui.Modifier
import android.view.KeyEvent
import androidx.test.espresso.Espresso
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import org.junit.Rule
import org.junit.Test
import org.junit.Assert.assertEquals

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
        Espresso.pressKey(KeyEvent.KEYCODE_DPAD_DOWN)
        compose.onNodeWithTag("server1").performSemanticsAction(SemanticsActions.RequestFocus)
        compose.onNodeWithTag("server1").assertIsFocused()
        Espresso.pressKey(KeyEvent.KEYCODE_DPAD_CENTER)
        compose.runOnIdle { assertEquals(1, selected) }
        Espresso.pressKey(KeyEvent.KEYCODE_DPAD_DOWN)
        compose.onNodeWithTag("server2").assertIsFocused()
        Espresso.pressKey(KeyEvent.KEYCODE_DPAD_CENTER)
        compose.runOnIdle { assertEquals(2, selected) }
        Espresso.pressKey(KeyEvent.KEYCODE_DPAD_DOWN)
        compose.onNodeWithTag("connect").assertIsFocused()
        Espresso.pressKey(KeyEvent.KEYCODE_DPAD_CENTER)
        compose.runOnIdle { assertEquals(1, connects) }
        Espresso.pressKey(KeyEvent.KEYCODE_DPAD_DOWN)
        compose.onNodeWithTag("menu").assertIsFocused()
        Espresso.pressKey(KeyEvent.KEYCODE_DPAD_CENTER)
        compose.runOnIdle { assertEquals(1, menus) }
        Espresso.pressKey(KeyEvent.KEYCODE_DPAD_UP)
        compose.onNodeWithTag("connect").assertIsFocused()
    }
}
