package com.adm.kiosk.util

import android.app.Activity
import android.app.role.RoleManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.util.Log

/**
 * Helpers to make the app the Android HOME launcher, so the system itself opens it on
 * every start-up (including after a power cut) and on every HOME press.
 */
object HomeLauncher {

    private const val TAG = "HomeLauncher"
    private const val REQUEST_HOME_ROLE = 4711

    /** Is this app currently the default HOME (launcher)? */
    fun isDefaultHome(context: Context): Boolean {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val rm = context.getSystemService(RoleManager::class.java)
            if (rm != null && rm.isRoleAvailable(RoleManager.ROLE_HOME)) {
                return rm.isRoleHeld(RoleManager.ROLE_HOME)
            }
        }
        val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME)
        val info = context.packageManager.resolveActivity(intent, PackageManager.MATCH_DEFAULT_ONLY)
        return info?.activityInfo?.packageName == context.packageName
    }

    /**
     * Asks Android to make this app the default launcher. Uses the official system dialog
     * when available and falls back to the HOME settings / chooser on older firmwares.
     * Returns false when no method is available on this device.
     */
    fun requestDefaultHome(activity: Activity): Boolean {
        // Lock Task blocks system dialogs from other packages.
        runCatching { activity.stopLockTask() }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val rm = activity.getSystemService(RoleManager::class.java)
            if (rm != null && rm.isRoleAvailable(RoleManager.ROLE_HOME) &&
                !rm.isRoleHeld(RoleManager.ROLE_HOME)
            ) {
                if (tryStart(activity, rm.createRequestRoleIntent(RoleManager.ROLE_HOME), REQUEST_HOME_ROLE)) {
                    return true
                }
            }
        }
        if (tryStart(activity, Intent(Settings.ACTION_HOME_SETTINGS))) return true
        return showHomeChooser(activity)
    }

    /**
     * Toggling a dummy HOME component makes Android forget the current default launcher, so
     * the next HOME press shows the "choose launcher" dialog.
     */
    private fun showHomeChooser(activity: Activity): Boolean {
        return try {
            val pm = activity.packageManager
            val fake = ComponentName(activity, "com.adm.kiosk.ui.kiosk.FakeHome")
            pm.setComponentEnabledSetting(fake, PackageManager.COMPONENT_ENABLED_STATE_ENABLED, PackageManager.DONT_KILL_APP)
            val home = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            activity.startActivity(home)
            pm.setComponentEnabledSetting(fake, PackageManager.COMPONENT_ENABLED_STATE_DISABLED, PackageManager.DONT_KILL_APP)
            true
        } catch (e: Exception) {
            Log.w(TAG, "HOME chooser unavailable", e)
            false
        }
    }

    /**
     * On Android 10+ an app that is not the launcher can only open itself at boot when it is
     * allowed to "display over other apps".
     */
    fun canStartFromBackground(context: Context): Boolean =
        Build.VERSION.SDK_INT < Build.VERSION_CODES.Q || Settings.canDrawOverlays(context)

    fun openOverlayPermission(activity: Activity): Boolean {
        runCatching { activity.stopLockTask() }
        val intent = Intent(
            Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
            Uri.parse("package:${activity.packageName}"),
        )
        return tryStart(activity, intent)
    }

    @Suppress("DEPRECATION")
    private fun tryStart(activity: Activity, intent: Intent, requestCode: Int? = null): Boolean {
        return try {
            if (intent.resolveActivity(activity.packageManager) == null) return false
            if (requestCode != null) activity.startActivityForResult(intent, requestCode)
            else activity.startActivity(intent)
            true
        } catch (e: Exception) {
            Log.w(TAG, "Cannot start ${intent.action}", e)
            false
        }
    }
}
