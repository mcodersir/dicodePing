package com.v2ray.ang.ui.main

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.v2ray.ang.R

/** A real, cancellable preparation pass; progress comes from the test service. */
@Composable
internal fun PreparationScreen(state: MainUiState, onSkip: () -> Unit) {
    BackHandler(onBack = onSkip)
    Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
        Column(
            modifier = Modifier.fillMaxSize().safeDrawingPadding().padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            Text("DicodePing", style = MaterialTheme.typography.headlineLarge, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(12.dp))
            Text(stringResource(R.string.preparation_title), style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(24.dp))
            Card(shape = RoundedCornerShape(24.dp), modifier = Modifier.fillMaxWidth().widthIn(max = 480.dp)) {
                Column(Modifier.padding(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                    Text(stringResource(when (state.preparationStage) {
                        "latency" -> R.string.preparation_latency
                        "location" -> R.string.preparation_location
                        else -> R.string.preparation_refresh
                    }), style = MaterialTheme.typography.titleMedium)
                    val fraction = preparationFraction(state.preparationProgress)
                    if (fraction == null) LinearProgressIndicator(Modifier.fillMaxWidth())
                    else LinearProgressIndicator(progress = { fraction }, modifier = Modifier.fillMaxWidth())
                    if (state.preparationProgress.isNotBlank()) Text(state.preparationProgress,
                        style = MaterialTheme.typography.bodyMedium)
                    Text(stringResource(R.string.preparation_hint), style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            Spacer(Modifier.height(24.dp))
            OutlinedButton(onClick = onSkip) { Text(stringResource(R.string.preparation_skip)) }
        }
    }
}

internal fun preparationFraction(text: String): Float? {
    val match = Regex("(\\d+)\\s*/\\s*(\\d+)").find(text) ?: return null
    val completed = match.groupValues[1].toFloatOrNull() ?: return null
    val total = match.groupValues[2].toFloatOrNull() ?: return null
    return if (total > 0) (completed / total).coerceIn(0f, 1f) else null
}
