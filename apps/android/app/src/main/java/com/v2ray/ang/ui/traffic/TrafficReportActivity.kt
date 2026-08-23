package com.v2ray.ang.ui.traffic

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.LayoutDirection
import com.v2ray.ang.R
import com.v2ray.ang.extension.toTrafficString
import com.v2ray.ang.handler.MmkvManager
import com.v2ray.ang.handler.TrafficStatsManager
import com.v2ray.ang.ui.base.HelperBaseComponentActivity
import com.v2ray.ang.ui.compose.AppTopBar

class TrafficReportActivity : HelperBaseComponentActivity() {
    @Composable
    override fun ScreenContent() {
        val reports = TrafficStatsManager.todayAll()
        Scaffold(topBar = { AppTopBar(stringResource(R.string.title_traffic_report), { finish() }) }) { padding ->
            LazyColumn(Modifier.fillMaxSize().padding(padding).padding(horizontal = 12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(reports, key = { it.first }) { (guid, traffic) ->
                    val name = MmkvManager.decodeServerConfig(guid)?.remarks ?: guid.take(8)
                    Card(Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(14.dp)) {
                            Text(name, style = MaterialTheme.typography.titleMedium)
                            CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Ltr) {
                                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                                    Text("↑ ${traffic.upload.toTrafficString()}", color = MaterialTheme.colorScheme.onSurfaceVariant)
                                    Text("↓ ${traffic.download.toTrafficString()}", color = MaterialTheme.colorScheme.onSurfaceVariant)
                                }
                            }
                        }
                    }
                }
                if (reports.isEmpty()) item { Text(stringResource(R.string.traffic_report_empty), Modifier.padding(20.dp)) }
            }
        }
    }
}
