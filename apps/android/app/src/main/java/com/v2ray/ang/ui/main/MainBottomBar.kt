package com.v2ray.ang.ui.main

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.spacedBy
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.AbsoluteAlignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.v2ray.ang.R
import com.v2ray.ang.ui.compose.AppDivider
import com.v2ray.ang.ui.compose.colorFabActive
import com.v2ray.ang.ui.compose.colorFabInactiveDark
import com.v2ray.ang.ui.compose.colorFabInactiveLight

@Composable
fun MainBottomBar(
    displayText: String,
    isRunning: Boolean,
    isDarkTheme: Boolean,
    isAutoConnecting: Boolean,
    onAction: (MainAction) -> Unit,
    onManualConnect: () -> Unit,
    onAutoConnect: () -> Unit,
    onLocationTest: () -> Unit,
) {
    Box(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .background(MaterialTheme.colorScheme.surface)
                .clickable(onClick = { onAction(MainAction.TestCurrentServer) })
                .windowInsetsPadding(WindowInsets.navigationBars)
        ) {
            AppDivider()
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(64.dp)
                    .padding(horizontal = 16.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Column {
                    Text(
                        text = displayText,
                        style = MaterialTheme.typography.bodyMedium,
                        modifier = Modifier.semantics {
                            contentDescription = displayText
                        }
                    )
                    Text(
                        text = stringResource(R.string.fab_location_beta),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.primary,
                        modifier = Modifier
                            .padding(top = 2.dp)
                            .clickable(onClick = onLocationTest)
                    )
                }
            }
        }
        Column(
            modifier = Modifier
                .align(AbsoluteAlignment.TopRight)
                .padding(end = 18.dp)
                // Keep both actions clear of the connection/status panel.
                .offset(y = (-144).dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
            horizontalAlignment = Alignment.End,
        ) {
            ExtendedFloatingActionButton(
                onClick = onAutoConnect,
                containerColor = if (isRunning) colorFabActive
                else if (isDarkTheme) colorFabInactiveDark
                else colorFabInactiveLight,
                icon = {
                    Icon(
                        painter = if (isRunning) painterResource(R.drawable.ic_stop_24dp)
                        else painterResource(R.drawable.ic_flash_on_24dp),
                        contentDescription = stringResource(if (isRunning) R.string.acc_stop else R.string.fab_auto_connect_best),
                        tint = if (!isRunning && isDarkTheme) Color(0xFF111820) else Color.White,
                        modifier = Modifier.size(22.dp)
                    )
                },
                text = {
                    Text(
                        text = when {
                            isRunning -> stringResource(R.string.acc_stop)
                            isAutoConnecting -> stringResource(R.string.fab_finding_best)
                            else -> stringResource(R.string.fab_auto_connect_best)
                        },
                        color = if (!isRunning && isDarkTheme) Color(0xFF111820) else Color.White,
                        style = MaterialTheme.typography.labelMedium,
                    )
                },
            )
            FloatingActionButton(
                onClick = onManualConnect,
                containerColor = if (isRunning) colorFabActive
                else MaterialTheme.colorScheme.primary,
            ) {
                Icon(
                    painter = if (isRunning) painterResource(R.drawable.ic_stop_24dp)
                    else painterResource(R.drawable.ic_play_24dp),
                    contentDescription = stringResource(if (isRunning) R.string.acc_stop else R.string.fab_manual_connect),
                    tint = Color.White,
                )
            }
        }
    }
}
