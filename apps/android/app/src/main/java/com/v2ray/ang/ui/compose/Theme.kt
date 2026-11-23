package com.v2ray.ang.ui.compose

import android.app.Activity
import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Shapes
import androidx.compose.ui.unit.dp
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
import androidx.compose.ui.text.intl.Locale
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

private val DarkGlass = DarkColor.copy(
    background = Color(0xFF141416), onBackground = Color(0xFFF8F7F5),
    surface = Color(0xFF202022), onSurface = Color(0xFFF8F7F5),
    primary = Color(0xFFF8F7F5), onPrimary = Color(0xFF1D1C1A),
    primaryContainer = Color(0xFF3D3123), onPrimaryContainer = Color(0xFFFFD9AA),
    secondaryContainer = Color(0xFF37342F), onSecondaryContainer = Color(0xFFF3DEBF),
    surfaceVariant = Color(0xFF302F32), onSurfaceVariant = Color(0xFFCCC9C7),
    outline = Color(0xFF989492), outlineVariant = Color(0xFF4C4849),
    surfaceTint = Color(0xFFDCCBB5), surfaceContainer = Color(0xFF232225),
    surfaceContainerLowest = Color(0xFF141416), surfaceContainerLow = Color(0xFF1C1B1E),
    surfaceContainerHigh = Color(0xFF2B2A2D), surfaceContainerHighest = Color(0xFF333235),
)

private val LightGlass = LightColor.copy(
    background = Color(0xFFF3F1EE), onBackground = Color(0xFF222120),
    surface = Color(0xFFFBFAF8), onSurface = Color(0xFF222120),
    primary = Color(0xFF272522), onPrimary = Color.White,
    primaryContainer = Color(0xFFFCE2C4), onPrimaryContainer = Color(0xFF452D17),
    secondaryContainer = Color(0xFFF2E5D5), onSecondaryContainer = Color(0xFF453727),
    surfaceVariant = Color(0xFFEBE7E2), onSurfaceVariant = Color(0xFF5E5752),
    outline = Color(0xFF746D65), outlineVariant = Color(0xFFD6CEC4),
    surfaceTint = Color(0xFF8C6D4E), surfaceContainer = Color(0xFFEFECE8),
    surfaceContainerLowest = Color.White, surfaceContainerLow = Color(0xFFF7F5F2),
    surfaceContainerHigh = Color(0xFFE9E5DF), surfaceContainerHighest = Color(0xFFE4DED6),
)

private val ClassicShapes = Shapes()
private val GlassShapes = Shapes(
    extraSmall = RoundedCornerShape(6.dp), small = RoundedCornerShape(10.dp),
    medium = RoundedCornerShape(16.dp), large = RoundedCornerShape(22.dp),
    extraLarge = RoundedCornerShape(28.dp),
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

// Toast Colors 85%
val toastNormalBgLight = Color(0xD9353A3E) // Dark Gray
val toastNormalBgDark = Color(0xD94A4F54) // Darker Gray
val toastSuccessBg = Color(0xD9388E3C) // Green
val toastErrorBg = Color(0xD9D50000) // Red
val toastInfoBg = Color(0xD93F51B5) // Indigo Blue
val toastIconCircleBg = Color(0x33FFFFFF) // Semi-transparent White
val toastTextColor = Color.White // White

object ThemeManager {
    private const val AppearanceKey = "dicode-appearance-style"
    private fun storedAppearance() = MmkvManager.decodeSettingsString(AppearanceKey, "")
        ?.takeIf { it == "classic" || it == "glass" }
    private val _appearanceStyle = MutableStateFlow(storedAppearance())
    val appearanceStyle: StateFlow<String?> = _appearanceStyle.asStateFlow()

    fun useGlassAppearance(enabled: Boolean) {
        val style = if (enabled) "glass" else "classic"
        MmkvManager.encodeSettings(AppearanceKey, style)
        _appearanceStyle.value = style
    }

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
        _appearanceStyle.value = storedAppearance()
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
val LocalGlassAppearance = compositionLocalOf { false }

private val VazirmatnFamily = FontFamily(
    Font(com.v2ray.ang.R.font.vazirmatn_regular, FontWeight.Normal),
    Font(com.v2ray.ang.R.font.vazirmatn_medium, FontWeight.Medium),
    Font(com.v2ray.ang.R.font.vazirmatn_bold, FontWeight.Bold),
)

private val OpenSansFamily = FontFamily(
    Font(com.v2ray.ang.R.font.open_sans_variable, FontWeight.Normal),
    Font(com.v2ray.ang.R.font.open_sans_variable, FontWeight.Medium),
    Font(com.v2ray.ang.R.font.open_sans_variable, FontWeight.Bold),
)

private fun appStyle(
    size: Int,
    family: FontFamily,
    weight: FontWeight = FontWeight.Normal,
    sizeAdjustment: Int = 0,
) = TextStyle(
    fontFamily = family,
    fontWeight = weight,
    fontSize = (size + sizeAdjustment).sp,
    lineHeight = (size + sizeAdjustment + 7).sp,
)

private fun dicodeTypography(family: FontFamily, adjustment: Int) = Typography(
    displayLarge = appStyle(54, family, FontWeight.Bold, adjustment), displayMedium = appStyle(44, family, FontWeight.Bold, adjustment), displaySmall = appStyle(34, family, FontWeight.Bold, adjustment),
    headlineLarge = appStyle(30, family, FontWeight.Bold, adjustment), headlineMedium = appStyle(26, family, FontWeight.Bold, adjustment), headlineSmall = appStyle(22, family, FontWeight.Bold, adjustment),
    titleLarge = appStyle(20, family, FontWeight.Bold, adjustment), titleMedium = appStyle(16, family, FontWeight.Medium, adjustment), titleSmall = appStyle(14, family, FontWeight.Medium, adjustment),
    bodyLarge = appStyle(16, family, sizeAdjustment = adjustment), bodyMedium = appStyle(14, family, sizeAdjustment = adjustment), bodySmall = appStyle(12, family, sizeAdjustment = adjustment),
    labelLarge = appStyle(14, family, FontWeight.Medium, adjustment), labelMedium = appStyle(12, family, FontWeight.Medium, adjustment), labelSmall = appStyle(10, family, FontWeight.Medium, adjustment),
)

@Composable
fun AppTheme(
    darkTheme: Boolean = resolveDarkTheme(),
    content: @Composable () -> Unit
) {
    val dynamicColor by ThemeManager.dynamicColorEnabled.collectAsState()
    val context = LocalContext.current
    val appearance by ThemeManager.appearanceStyle.collectAsState()
    val useGlass = appearance == "glass"
    val colorScheme = when {
        useGlass -> if (darkTheme) DarkGlass else LightGlass
        dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> {
            if (darkTheme) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        }

        darkTheme -> DarkColor
        else -> LightColor
    }
    val snackbarController = rememberAppSnackbarController()
    val isPersian = Locale.current.language.equals("fa", ignoreCase = true)
    val typography = dicodeTypography(
        family = if (isPersian) VazirmatnFamily else OpenSansFamily,
        adjustment = if (isPersian) 0 else 1,
    )

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
        LocalGlassAppearance provides useGlass,
        LocalAppSnackbar provides snackbarController
    ) {
        MaterialTheme(
            colorScheme = colorScheme,
            typography = typography,
            shapes = if (useGlass) GlassShapes else ClassicShapes,
        ) {
            Box(modifier = Modifier.fillMaxSize()) {
                AppSnackbarBridge(controller = snackbarController)
                content()
                AppSnackbarHost(hostState = snackbarController.hostState)
            }
        }
    }
}
