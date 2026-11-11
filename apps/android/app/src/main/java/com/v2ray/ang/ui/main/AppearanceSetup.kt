package com.v2ray.ang.ui.main

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.res.stringArrayResource
import androidx.compose.ui.unit.dp
import com.v2ray.ang.AppConfig
import com.v2ray.ang.R
import com.v2ray.ang.handler.MmkvManager

internal const val APPEARANCE_SETUP_503 = "dicode_appearance_setup_503"

/** Kept version-scoped: upgrading to 5.0.3 asks once; activity recreation does not. */
@Composable
internal fun AppearanceSetup(onComplete: (String, String) -> Unit) {
    var language by remember { mutableStateOf(MmkvManager.decodeSettingsString(AppConfig.PREF_LANGUAGE) ?: "en") }
    var theme by remember { mutableStateOf(MmkvManager.decodeSettingsString(AppConfig.PREF_UI_MODE_NIGHT) ?: "0") }
    val names = stringArrayResource(R.array.language_select)
    val values = stringArrayResource(R.array.language_select_value)
    Surface(Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize().safeDrawingPadding().padding(20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            Text("Welcome to DicodePing", style = MaterialTheme.typography.headlineSmall)
            Text("زبان و ظاهر · Language & appearance", style = MaterialTheme.typography.titleMedium)
            Column(Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState())) {
                names.forEachIndexed { index, label ->
                    val value = values[index]
                    Row(Modifier.fillMaxWidth().selectable(language == value, role = Role.RadioButton, onClick = { language = value }).padding(vertical = 4.dp)) {
                        RadioButton(selected = language == value, onClick = null, modifier = Modifier.padding(12.dp))
                        Text(label, Modifier.padding(vertical = 16.dp).weight(1f))
                    }
                }
                HorizontalDivider(Modifier.padding(vertical = 12.dp))
                listOf("0" to "System · سیستم", "1" to "Light · روشن", "2" to "Dark · تیره").forEach { (value, label) ->
                    Row(Modifier.fillMaxWidth().selectable(theme == value, role = Role.RadioButton, onClick = { theme = value }).padding(vertical = 4.dp)) {
                        RadioButton(theme == value, onClick = null, modifier = Modifier.padding(12.dp))
                        Text(label, Modifier.padding(vertical = 16.dp).weight(1f))
                    }
                }
            }
            Button(onClick = { onComplete(language, theme) }, modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp)) { Text("Continue · ادامه") }
        }
    }
}
