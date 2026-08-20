package com.v2ray.ang.ui.domainfilter

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.v2ray.ang.AppConfig
import com.v2ray.ang.R
import com.v2ray.ang.core.LauncherManager
import com.v2ray.ang.extension.toastSuccess
import com.v2ray.ang.handler.MmkvManager
import com.v2ray.ang.ui.base.HelperBaseComponentActivity
import com.v2ray.ang.ui.compose.AppTopBar
import com.v2ray.ang.ui.compose.SettingsSwitchItem

class DomainFilterActivity : HelperBaseComponentActivity() {
    @Composable
    override fun ScreenContent() {
        var mode by remember { mutableStateOf(MmkvManager.decodeSettingsString(AppConfig.PREF_DOMAIN_FILTER_MODE) ?: "off") }
        var domains by remember { mutableStateOf(MmkvManager.decodeSettingsString(AppConfig.PREF_DOMAIN_FILTER_LIST).orEmpty()) }
        Scaffold(topBar = { AppTopBar(stringResource(R.string.title_domain_filter), { finish() }) }) { padding ->
            Column(Modifier.fillMaxSize().padding(padding).padding(horizontal = 16.dp)) {
                SettingsSwitchItem(
                    title = stringResource(R.string.domain_filter_only), checked = mode == "only",
                    onCheckedChange = { mode = if (it) "only" else "off" }
                )
                SettingsSwitchItem(
                    title = stringResource(R.string.domain_filter_bypass), checked = mode == "bypass",
                    onCheckedChange = { mode = if (it) "bypass" else "off" }
                )
                OutlinedTextField(
                    value = domains, onValueChange = { domains = it },
                    label = { Text(stringResource(R.string.title_pref_domain_filter_list)) },
                    minLines = 8, modifier = Modifier.fillMaxWidth().weight(1f).padding(vertical = 12.dp)
                )
                Button(onClick = {
                    val normalized = domains.split('\n', '\r', ',', ' ', '\t')
                        .map { it.trim().trimStart('.') }.filter { it.isNotEmpty() }.distinct().joinToString("\n")
                    MmkvManager.encodeSettings(AppConfig.PREF_DOMAIN_FILTER_MODE, mode)
                    MmkvManager.encodeSettings(AppConfig.PREF_DOMAIN_FILTER_LIST, normalized)
                    LauncherManager.restartService(this@DomainFilterActivity)
                    toastSuccess(R.string.toast_success)
                    finish()
                }, modifier = Modifier.fillMaxWidth().padding(bottom = 16.dp)) {
                    Text(stringResource(R.string.save_and_apply))
                }
            }
        }
    }
}
