package com.v2ray.ang.ui.main

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Density
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import org.junit.Rule
import org.junit.Test
import org.junit.Assert.assertEquals

class FoxCountrySearchTest {
    @get:Rule val compose = createComposeRule()
    @Test fun countrySearchAndSelectionWorkAtTwiceTheFontSize() {
        var selected = ""
        compose.setContent {
            CompositionLocalProvider(LocalDensity provides Density(LocalDensity.current.density, 2f)) {
                MaterialTheme {
                    FoxCountryDialog(listOf("REC", "DE", "JP"), { when(it) { "DE" -> "آلمان · DE"; "JP" -> "ژاپن · JP"; else -> "پیشنهادی" } }, true,
                        onDismiss = {}, onSelect = { selected = it })
                }
            }
        }
        compose.onNodeWithTag("country-search").performTextInput("ژاپن")
        compose.onNodeWithTag("country-DE").assertDoesNotExist()
        compose.onNodeWithTag("country-JP").performScrollTo().assertIsDisplayed().performClick()
        compose.runOnIdle { assertEquals("JP", selected) }
        compose.onNodeWithTag("country-search").performTextReplacement("de")
        compose.onNodeWithTag("country-DE").performScrollTo().assertIsDisplayed()
    }
}
