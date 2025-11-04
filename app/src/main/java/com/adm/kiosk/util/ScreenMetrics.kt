package com.adm.kiosk.util

import android.content.Context
import android.util.DisplayMetrics
import android.view.WindowManager

/**
 * Detects the physical screen characteristics so the WebView content can be scaled
 * appropriately across HD / FHD / 2K / 4K panels and projectors.
 */
data class ScreenInfo(
    val widthPx: Int,
    val heightPx: Int,
    val densityDpi: Int,
) {
    val is4kClass: Boolean get() = widthPx >= 3000 || heightPx >= 3000
    val is2kClass: Boolean get() = !is4kClass && (widthPx >= 2000 || heightPx >= 2000)
    val isFullHdClass: Boolean get() = !is2kClass && !is4kClass && widthPx >= 1600

    /**
     * Suggests an initial WebView text-zoom / density multiplier so that a page designed for a
     * 1080p canvas remains readable on very high resolution panels seen from a distance.
     */
    fun suggestedAutoZoomPercent(): Int = when {
        is4kClass -> 200
        is2kClass -> 150
        isFullHdClass -> 100
        else -> 100
    }
}

object ScreenMetrics {

    @Suppress("DEPRECATION")
    fun of(context: Context): ScreenInfo {
        val wm = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
        val metrics = DisplayMetrics()
        wm.defaultDisplay.getRealMetrics(metrics)
        return ScreenInfo(
            widthPx = metrics.widthPixels,
            heightPx = metrics.heightPixels,
            densityDpi = metrics.densityDpi,
        )
    }
}
