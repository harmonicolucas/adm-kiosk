package com.adm.kiosk.util

import android.app.UiModeManager
import android.content.Context
import android.content.res.Configuration
import android.content.pm.PackageManager

/**
 * Detects whether the app is running on a television-class device (Android TV, TV box,
 * leanback). Used to avoid trapping ordinary phones/tablets in kiosk (screen pinning)
 * or auto-launching on boot.
 */
object DeviceType {

    fun isTelevision(context: Context): Boolean {
        val pm = context.packageManager
        val uiMode = context.getSystemService(Context.UI_MODE_SERVICE) as? UiModeManager
        val uiIsTv = uiMode?.currentModeType == Configuration.UI_MODE_TYPE_TELEVISION
        val hasLeanback = pm.hasSystemFeature(PackageManager.FEATURE_LEANBACK) ||
            pm.hasSystemFeature("android.software.leanback")
        val hasTvFeature = pm.hasSystemFeature("android.hardware.type.television")
        return uiIsTv || hasLeanback || hasTvFeature
    }
}
