package com.v2ray.ang.ui.compose

import android.app.Activity
import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.material3.Typography
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import androidx.core.view.WindowCompat
import com.v2ray.ang.AppConfig
import com.v2ray.ang.handler.MmkvManager
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

private val LightColor = lightColorScheme(
    primary = Color(0xFF202832), onPrimary = Color.White,
    primaryContainer = Color(0xFFE3E7EC), onPrimaryContainer = Color(0xFF11171D),
    secondary = Color(0xFF667381), onSecondary = Color.White,
    secondaryContainer = Color(0xFFE7EBEF), onSecondaryContainer = Color(0xFF1D252E),
    tertiary = Color(0xFF087C5D), onTertiary = Color.White,
    tertiaryContainer = Color(0xFFC5F2E2), onTertiaryContainer = Color(0xFF002118),
    error = Color(0xFFB3263E), errorContainer = Color(0xFFFFD9DE),
    onError = Color.White, onErrorContainer = Color(0xFF41000D),
    background = Color(0xFFF5F6F8), onBackground = Color(0xFF151A20),
    surface = Color(0xFFFAFBFC), onSurface = Color(0xFF151A20),
    surfaceVariant = Color(0xFFE7EBEF), onSurfaceVariant = Color(0xFF56616D),
    outline = Color(0xFF7A8693), outlineVariant = Color(0xFFD8DDE3),
    inverseSurface = Color(0xFF20272F), inverseOnSurface = Color(0xFFF2F4F7),
    inversePrimary = Color(0xFFC6CED7), scrim = Color.Black,
    surfaceTint = Color(0xFF202832), surfaceContainerLowest = Color.White,
    surfaceContainerLow = Color(0xFFF0F2F5), surfaceContainer = Color(0xFFECEFF2),
    surfaceContainerHigh = Color(0xFFE5E9ED), surfaceContainerHighest = Color(0xFFDDE2E7),
)

private val DarkColor = darkColorScheme(
    primary = Color(0xFFD7DDE5), onPrimary = Color(0xFF111820),
    primaryContainer = Color(0xFF28323D), onPrimaryContainer = Color(0xFFE9EDF2),
    secondary = Color(0xFF9AA6B4), onSecondary = Color(0xFF172029),
    secondaryContainer = Color(0xFF26313B), onSecondaryContainer = Color(0xFFDCE2E8),
    tertiary = Color(0xFF52D6A3), onTertiary = Color(0xFF003827),
    tertiaryContainer = Color(0xFF07513D), onTertiaryContainer = Color(0xFFB9F2DD),
    error = Color(0xFFFFB2BC), errorContainer = Color(0xFF8C1028),
    onError = Color(0xFF650018), onErrorContainer = Color(0xFFFFD9DE),
    background = Color(0xFF0B0F14), onBackground = Color(0xFFF2F4F7),
    surface = Color(0xFF10161D), onSurface = Color(0xFFF2F4F7),
    surfaceVariant = Color(0xFF252E38), onSurfaceVariant = Color(0xFFADB7C2),
    outline = Color(0xFF7E8996), outlineVariant = Color(0xFF27313D),
    inverseSurface = Color(0xFFE5E9ED), inverseOnSurface = Color(0xFF1B222A),
    inversePrimary = Color(0xFF4C5966), scrim = Color.Black,
    surfaceTint = Color(0xFFD7DDE5), surfaceContainerLowest = Color(0xFF080B0F),
    surfaceContainerLow = Color(0xFF0D1218), surfaceContainer = Color(0xFF11171E),
    surfaceContainerHigh = Color(0xFF151C24), surfaceContainerHighest = Color(0xFF1A222C),
)

// Semantic Colors
val colorPing = Color(0xFF22A878)
val colorPingRed = Color(0xFFE45D70)
val colorConfigType = Color(0xFF8E99A6)
val colorFabActive = Color(0xFF52D6A3)
val colorFabInactiveLight = Color(0xFF202832)
val colorFabInactiveDark = Color(0xFFD7DDE5)
val dividerColorLight = Color(0xFFE0E0E0) // Light Gray
val dividerColorDark = Color(0xFF424242) // Dark Gray

// Toast Colors 70%
val toastNormalBgLight = Color(0xB3353A3E) // Dark Gray
val toastNormalBgDark = Color(0xB34A4F54) // Darker Gray
val toastSuccessBg = Color(0xB3388E3C) // Green
val toastErrorBg = Color(0xB3D50000) // Red
val toastInfoBg = Color(0xB33F51B5) // Indigo Blue
val toastIconCircleBg = Color(0x33FFFFFF) // Semi-transparent White
val toastTextColor = Color.White // White

object ThemeManager {
    private val _themeMode = MutableStateFlow(
        MmkvManager.decodeSettingsString(AppConfig.PREF_UI_MODE_NIGHT, "0") ?: "0"
    )
    val themeMode: StateFlow<String> = _themeMode.asStateFlow()

    private val _dynamicColorEnabled = MutableStateFlow(
        MmkvManager.decodeSettingsBool(AppConfig.PREF_DYNAMIC_COLOR, false)
    )
    val dynamicColorEnabled: StateFlow<Boolean> = _dynamicColorEnabled.asStateFlow()

    fun setThemeMode(mode: String) {
        MmkvManager.encodeSettings(AppConfig.PREF_UI_MODE_NIGHT, mode)
        _themeMode.value = mode
    }

    fun setDynamicColorEnabled(enabled: Boolean) {
        MmkvManager.encodeSettings(AppConfig.PREF_DYNAMIC_COLOR, enabled)
        _dynamicColorEnabled.value = enabled
    }

    fun refresh() {
        _themeMode.value =
            MmkvManager.decodeSettingsString(AppConfig.PREF_UI_MODE_NIGHT, "0") ?: "0"
        _dynamicColorEnabled.value =
            MmkvManager.decodeSettingsBool(AppConfig.PREF_DYNAMIC_COLOR, false)
    }
}

@Composable
fun resolveDarkTheme(): Boolean {
    val mode by ThemeManager.themeMode.collectAsState()
    return when (mode) {
        "1" -> false
        "2" -> true
        else -> isSystemInDarkTheme()
    }
}

val LocalDarkTheme = compositionLocalOf { false }

private val VazirmatnFamily = FontFamily(
    Font(com.v2ray.ang.R.font.vazirmatn_regular, FontWeight.Normal),
    Font(com.v2ray.ang.R.font.vazirmatn_medium, FontWeight.Medium),
    Font(com.v2ray.ang.R.font.vazirmatn_bold, FontWeight.Bold),
)

private fun vazirStyle(size: Int, weight: FontWeight = FontWeight.Normal) = TextStyle(
    fontFamily = VazirmatnFamily,
    fontWeight = weight,
    fontSize = size.sp,
    lineHeight = (size + 7).sp,
)

private val DicodeTypography = Typography(
    displayLarge = vazirStyle(54, FontWeight.Bold), displayMedium = vazirStyle(44, FontWeight.Bold), displaySmall = vazirStyle(34, FontWeight.Bold),
    headlineLarge = vazirStyle(30, FontWeight.Bold), headlineMedium = vazirStyle(26, FontWeight.Bold), headlineSmall = vazirStyle(22, FontWeight.Bold),
    titleLarge = vazirStyle(20, FontWeight.Bold), titleMedium = vazirStyle(16, FontWeight.Medium), titleSmall = vazirStyle(14, FontWeight.Medium),
    bodyLarge = vazirStyle(16), bodyMedium = vazirStyle(14), bodySmall = vazirStyle(12),
    labelLarge = vazirStyle(14, FontWeight.Medium), labelMedium = vazirStyle(12, FontWeight.Medium), labelSmall = vazirStyle(10, FontWeight.Medium),
)

@Composable
fun AppTheme(
    darkTheme: Boolean = resolveDarkTheme(),
    content: @Composable () -> Unit
) {
    val dynamicColor by ThemeManager.dynamicColorEnabled.collectAsState()
    val context = LocalContext.current
    val colorScheme = when {
        dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> {
            if (darkTheme) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        }

        darkTheme -> DarkColor
        else -> LightColor
    }
    val snackbarController = rememberAppSnackbarController()

    val view = LocalView.current
    if (!view.isInEditMode) {
        SideEffect {
            val activity = view.context as? Activity ?: return@SideEffect
            val window = activity.window
            WindowCompat.getInsetsController(window, view).apply {
                isAppearanceLightStatusBars = !darkTheme
                isAppearanceLightNavigationBars = !darkTheme
            }
        }
    }

    CompositionLocalProvider(
        LocalDarkTheme provides darkTheme,
        LocalAppSnackbar provides snackbarController
    ) {
        MaterialTheme(
            colorScheme = colorScheme,
            typography = DicodeTypography,
        ) {
            Box(modifier = Modifier.fillMaxSize()) {
                AppSnackbarBridge(controller = snackbarController)
                content()
                AppSnackbarHost(hostState = snackbarController.hostState)
            }
        }
    }
}
