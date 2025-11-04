package com.adm.kiosk.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

private val AdmColorScheme = lightColorScheme(
    primary = AdmBlack,
    onPrimary = AdmWhite,
    secondary = AdmYellow,
    onSecondary = AdmBlack,
    tertiary = AdmGreen,
    background = AdmOffWhite,
    onBackground = AdmInk,
    surface = AdmWhite,
    onSurface = AdmInk,
    surfaceVariant = AdmOffWhite,
    onSurfaceVariant = AdmInkDim,
    error = AdmRed,
    onError = AdmWhite,
    outline = AdmBorder,
)

private val AdmTypography = Typography(
    headlineMedium = TextStyle(fontWeight = FontWeight.Bold, fontSize = 26.sp),
    titleLarge = TextStyle(fontWeight = FontWeight.SemiBold, fontSize = 20.sp),
    titleMedium = TextStyle(fontWeight = FontWeight.SemiBold, fontSize = 17.sp),
    bodyLarge = TextStyle(fontSize = 16.sp),
    bodyMedium = TextStyle(fontSize = 14.sp),
    labelLarge = TextStyle(fontWeight = FontWeight.SemiBold, fontSize = 15.sp),
)

@Composable
fun AdmKioskTheme(
    @Suppress("UNUSED_PARAMETER") darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    MaterialTheme(
        colorScheme = AdmColorScheme,
        typography = AdmTypography,
        content = content,
    )
}
