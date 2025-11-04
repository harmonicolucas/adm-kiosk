package com.adm.kiosk.kiosk

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.util.Log
import com.adm.kiosk.ui.kiosk.KioskActivity
import com.adm.kiosk.util.DeviceType

/**
 * Relaunches the kiosk automatically after the device boots (or after an app update).
 * When the app is the default launcher Android already opens it; this receiver covers
 * firmwares where another launcher is still the default.
 */
class BootReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val action = intent.action ?: return
        if (action !in START_ACTIONS) return

        // Do not auto-launch on ordinary phones/tablets; only on TV-class devices
        // or when provisioned as Device Owner (true kiosk deployment).
        if (!DeviceType.isTelevision(context) && !isDeviceOwner(context)) {
            Log.i(TAG, "Start event on non-TV / non-device-owner — skipping auto-launch")
            return
        }

        Log.i(TAG, "Start event ($action) — launching kiosk")
        launch(context)

        // The manufacturer launcher often appears a few seconds after BOOT_COMPLETED and
        // covers the kiosk; bring the kiosk back to the front once more.
        val pending = goAsync()
        Handler(Looper.getMainLooper()).postDelayed({
            launch(context)
            pending.finish()
        }, RELAUNCH_DELAY_MS)
    }

    private fun launch(context: Context) {
        val launch = Intent(context, KioskActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT)
        }
        try {
            context.startActivity(launch)
        } catch (e: Exception) {
            Log.w(TAG, "Failed to start kiosk", e)
        }
    }

    private fun isDeviceOwner(context: Context): Boolean {
        return try {
            val dpm = context.getSystemService(Context.DEVICE_POLICY_SERVICE)
                as android.app.admin.DevicePolicyManager
            dpm.isDeviceOwnerApp(context.packageName)
        } catch (e: Exception) {
            false
        }
    }

    companion object {
        private const val TAG = "BootReceiver"
        private const val RELAUNCH_DELAY_MS = 8_000L
        private val START_ACTIONS = setOf(
            Intent.ACTION_BOOT_COMPLETED,
            Intent.ACTION_MY_PACKAGE_REPLACED,
            "android.intent.action.QUICKBOOT_POWERON",
            "com.htc.intent.action.QUICKBOOT_POWERON",
        )
    }
}
