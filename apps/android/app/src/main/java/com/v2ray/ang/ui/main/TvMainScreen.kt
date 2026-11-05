package com.v2ray.ang.ui.main

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.v2ray.ang.R

/** A ten-foot interface: one focus target per action, no swipe or long-press. */
@Composable
internal fun TvMainScreen(
    viewModel: MainViewModel,
    onAction: (MainAction) -> Unit,
    onNavigate: (MainDestination) -> Unit,
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val groups = state.groups
    val groupState by viewModel.serverGroupState(state.selectedGroupId).collectAsStateWithLifecycle()
    val connectFocus = remember { FocusRequester() }
    var showFox by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { connectFocus.requestFocus() }
    LaunchedEffect(state.startupConnectGuid) {
        viewModel.consumeStartupConnection()?.let { if (!state.isRunning) onAction(MainAction.ConnectServer(it)) }
    }
    if (showFox) FoxScreen(
        isRunning = state.isRunning, onDismiss = { showFox = false },
        onChanged = { viewModel.setupGroupTab(forceRefresh = true) },
        onConnect = { onAction(MainAction.ConnectServer(it)) },
    )
    Surface(color = Color(0xFF101B30), contentColor = Color(0xFFF1F5FF)) {
        Row(Modifier.fillMaxSize().padding(horizontal = 40.dp, vertical = 24.dp), horizontalArrangement = Arrangement.spacedBy(32.dp)) {
            Column(Modifier.width(260.dp).fillMaxHeight().verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("DicodePing TV", style = MaterialTheme.typography.headlineMedium)
                Text(viewModel.formatStatus(state.status), style = MaterialTheme.typography.bodyLarge)
                TvAction(
                    text = stringResource(if (state.isRunning) R.string.tv_disconnect else R.string.tv_connect),
                    modifier = Modifier.focusRequester(connectFocus),
                    enabled = true,
                    onClick = { onAction(MainAction.ToggleService) },
                )
                TvAction(stringResource(R.string.title_sub_setting), onClick = { onNavigate(MainDestination.Subscriptions) })
                TvAction(stringResource(R.string.tv_update), onClick = { onAction(MainAction.UpdateSubscriptions) })
                TvAction(stringResource(R.string.tv_import), onClick = { onAction(MainAction.ImportClipboard) })
                TvAction(stringResource(R.string.tv_fox), onClick = { showFox = true })
                TvAction(stringResource(R.string.title_settings), onClick = { onNavigate(MainDestination.Settings) })
            }
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                Text(stringResource(R.string.tv_profiles), style = MaterialTheme.typography.headlineSmall)
                LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(groups, key = { it.id }) { group ->
                        TvAction(group.remarks, modifier = Modifier.widthIn(min = 100.dp, max = 240.dp), selected = group.id == state.selectedGroupId,
                            onClick = { onAction(MainAction.SelectGroup(group.id)) })
                    }
                }
                if (groupState.rows.isEmpty()) Text(stringResource(R.string.tv_empty), style = MaterialTheme.typography.bodyLarge)
                LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    items(groupState.rows, key = { it.guid }) { row ->
                        TvAction(
                            text = row.remarks,
                            selected = row.guid == state.selectedGuid,
                            onClick = { onAction(MainAction.SelectServer(row.guid)) },
                        )
                    }
                }
                Text(stringResource(R.string.tv_remote_hint), style = MaterialTheme.typography.bodyMedium)
            }
        }
    }
}

@Composable
private fun TvAction(text: String, modifier: Modifier = Modifier, enabled: Boolean = true, selected: Boolean = false, onClick: () -> Unit) {
    var focused by remember { mutableStateOf(false) }
    OutlinedButton(
        onClick = onClick, enabled = enabled,
        modifier = modifier.fillMaxWidth().heightIn(min = 52.dp).onFocusChanged { focused = it.isFocused },
        shape = RoundedCornerShape(12.dp),
        border = BorderStroke(if (focused) 3.dp else 1.dp, if (focused) Color(0xFF8DC7FF) else Color(0xFF46566F)),
        colors = ButtonDefaults.outlinedButtonColors(
            containerColor = if (focused) Color(0xFF284B73) else if (selected) Color(0xFF203956) else Color(0xFF17263C),
            contentColor = Color(0xFFF1F5FF), disabledContentColor = Color(0xFF98A6BA),
        ),
    ) { Text(text, style = MaterialTheme.typography.titleMedium, maxLines = 2) }
}
