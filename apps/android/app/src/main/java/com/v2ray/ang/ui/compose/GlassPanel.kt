package com.v2ray.ang.ui.compose

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

@Composable
internal fun Modifier.glassPanel(selected: Boolean = false): Modifier {
    val colors = MaterialTheme.colorScheme
    val shape = MaterialTheme.shapes.large
    val light = !LocalDarkTheme.current
    val rim = if (light) Color.White.copy(alpha = 0.94f) else colors.outline.copy(alpha = 0.78f)
    val fill = if (selected) colors.primaryContainer else colors.surface
    val base = if (selected) colors.secondaryContainer else colors.surfaceContainerHigh
    return clip(shape)
        .background(Brush.verticalGradient(listOf(fill.copy(alpha = 0.94f), base.copy(alpha = 0.74f))))
        .border(1.dp, Brush.verticalGradient(listOf(rim, colors.outlineVariant)), shape)
}
