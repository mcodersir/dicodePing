package com.v2ray.ang.ui.compose

import android.graphics.Paint
import android.graphics.RuntimeShader
import android.os.Build
import androidx.annotation.RequiresApi
import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.drawIntoCanvas
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInRoot
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.unit.dp

@Composable
internal fun Modifier.glassBackdrop(): Modifier = glassOptics(panel = false)

@Composable
internal fun Modifier.glassPanel(selected: Boolean = false): Modifier {
    val colors = MaterialTheme.colorScheme
    val shape = MaterialTheme.shapes.large
    val rim = Color.White.copy(alpha = if (LocalDarkTheme.current) 0.46f else 0.95f)
    val shadow = colors.outlineVariant.copy(alpha = 0.66f)
    return clip(shape)
        .glassOptics(panel = true, selected = selected)
        .border(1.dp, Brush.verticalGradient(listOf(rim, shadow, rim.copy(alpha = 0.28f))), shape)
}

@Composable
private fun Modifier.glassOptics(panel: Boolean, selected: Boolean = false): Modifier {
    val dark = LocalDarkTheme.current
    val configuration = LocalConfiguration.current
    val windowWidth = configuration.screenWidthDp.dp
    val windowHeight = configuration.screenHeightDp.dp
    val position = remember { mutableStateOf(Offset.Zero) }
    val tint = if (selected) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surface
    val positioned = if (panel) onGloballyPositioned { position.value = it.positionInRoot() } else this
    return positioned.drawWithCache {
        val origin = if (panel) position.value else Offset.Zero
        val worldWidth = if (panel) windowWidth.toPx() else size.width
        val worldHeight = if (panel) windowHeight.toPx() else size.height
        val paint = if (Build.VERSION.SDK_INT >= 33) {
            try {
                glassPaint(size.width, size.height, origin, worldWidth, worldHeight, dark, panel)
            } catch (_: IllegalArgumentException) {
                null
            }
        } else null
        val fallback = Brush.linearGradient(
            if (dark) listOf(Color(0xFF0C1426), Color(0xFF203A50), Color(0xFF19243D))
            else listOf(Color(0xFFF6F9FF), Color(0xFFDCEAF5), Color(0xFFE5E5F7))
        )
        onDrawBehind {
            if (!panel) drawRect(fallback)
            if (paint != null) {
                drawIntoCanvas {
                    val canvas = it.nativeCanvas
                    if (canvas.isHardwareAccelerated)
                        canvas.drawRect(0f, 0f, size.width, size.height, paint)
                }
            }
            if (panel) drawRect(tint.copy(alpha = if (selected) 0.58f else 0.34f))
        }
    }
}

@RequiresApi(33)
private fun glassPaint(
    width: Float, height: Float, origin: Offset, worldWidth: Float, worldHeight: Float,
    dark: Boolean, panel: Boolean
): Paint {
    val shader = RuntimeShader(GLASS_SHADER)
    shader.setFloatUniform("bounds", width.coerceAtLeast(1f), height.coerceAtLeast(1f))
    shader.setFloatUniform("origin", origin.x, origin.y)
    shader.setFloatUniform("viewport", worldWidth.coerceAtLeast(1f), worldHeight.coerceAtLeast(1f))
    shader.setFloatUniform("dark", if (dark) 1f else 0f)
    shader.setFloatUniform("panel", if (panel) 1f else 0f)
    return Paint().apply { this.shader = shader }
}

@Composable
internal fun GlassDropdownMenu(
    expanded: Boolean,
    onDismissRequest: () -> Unit,
    modifier: Modifier = Modifier,
    scrollState: ScrollState = rememberScrollState(),
    content: @Composable ColumnScope.() -> Unit
) {
    val glass = LocalGlassAppearance.current
    DropdownMenu(
        expanded = expanded,
        onDismissRequest = onDismissRequest,
        modifier = if (glass) modifier.glassPanel() else modifier,
        scrollState = scrollState,
        containerColor = if (glass) Color.Transparent else MaterialTheme.colorScheme.surface,
        tonalElevation = if (glass) 0.dp else 3.dp,
        content = content,
    )
}

private const val GLASS_SHADER = """
    uniform float2 bounds;
    uniform float2 origin;
    uniform float2 viewport;
    uniform float dark;
    uniform float panel;

    float3 scene(float2 pixel) {
        float2 uv = pixel / viewport;
        float a = exp(-5.5 * dot(uv - float2(0.1, 0.28), uv - float2(0.1, 0.28)));
        float b = exp(-6.0 * dot(uv - float2(0.92, 0.64), uv - float2(0.92, 0.64)));
        float wave = abs(uv.y - (0.43 + 0.16 * sin(5.2 * uv.x)));
        float ribbon = 1.0 - smoothstep(0.022, 0.10, wave);
        float3 day = float3(0.92, 0.95, 0.99) + a * float3(-0.08, -0.04, 0.0)
            + b * float3(-0.10, -0.04, -0.02) + ribbon * float3(-0.10, -0.065, -0.02);
        float3 night = float3(0.036, 0.054, 0.095) + a * float3(0.03, 0.12, 0.17)
            + b * float3(0.12, 0.10, 0.22) + ribbon * float3(0.04, 0.095, 0.13);
        return mix(day, night, dark);
    }

    half4 main(float2 pixel) {
        float2 world = origin + pixel;
        if (panel < 0.5) return half4(scene(world), 1.0);
        float2 q = pixel / bounds * 2.0 - 1.0;
        float2 edge = min(pixel, bounds - pixel);
        float d = min(edge.x, edge.y);
        float rim = 1.0 - smoothstep(0.0, 15.0, d);
        float2 normal = normalize(q + float2(0.0001, 0.0001));
        float2 bent = world - normal * (3.0 + 22.0 * rim);
        float3 blur = scene(bent) * 0.36
            + (scene(bent + float2(12.0, 0.0)) + scene(bent - float2(12.0, 0.0))
            + scene(bent + float2(0.0, 12.0)) + scene(bent - float2(0.0, 12.0))) * 0.16;
        float3 dispersion = float3(scene(bent + 4.0 * normal).r, blur.g, scene(bent - 4.0 * normal).b);
        float highlight = rim * (0.12 + 0.13 * max(0.0, -q.y));
        return half4(mix(blur, dispersion, rim * 0.3) + float3(highlight), 1.0);
    }
"""
