package com.adm.kiosk.kiosk

import android.app.Activity
import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.os.Build
import android.util.Log

/**
 * Central point for everything related to Lock Task (Kiosk) mode.
 *
 * Works in two tiers:
 *  1. **Device Owner** (recommended): a true kiosk. We can whitelist our package, hide system
 *     UI, and make the app the persistent HOME launcher so the Android menu is never reachable.
 *  2. **Fallback** (no device owner): we still call [Activity.startLockTask]. On most devices this
 *     shows a "screen pinning" style lock, combined with UI hiding done in the activity.
 */
class KioskManager(context: Context) {

    private val appContext = context.applicationContext
    private val dpm = appContext.getSystemService(Context.DEVICE_POLICY_SERVICE) as DevicePolicyManager
    private val admin: ComponentName = DeviceOwnerReceiver.componentName(appContext)

    fun isDeviceOwner(): Boolean = dpm.isDeviceOwnerApp(appContext.packageName)

    fun isLockTaskPermitted(): Boolean =
        if (isDeviceOwner()) dpm.isLockTaskPermitted(appContext.packageName) else false

    /** Whitelist our own package so Lock Task can be entered without the pinning prompt. */
    fun configureLockTaskPackages() {
        if (!isDeviceOwner()) return
        try {
            dpm.setLockTaskPackages(admin, arrayOf(appContext.packageName))
        } catch (e: SecurityException) {
            Log.w(TAG, "setLockTaskPackages failed", e)
        }
    }

    /**
     * Apply the strongest kiosk policies available. Safe to call multiple times.
     */
    fun applyDeviceOwnerPolicies() {
        if (!isDeviceOwner()) return
        configureLockTaskPackages()
        try {
            setAsPreferredHome()
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                // Allow a minimal set of system features while locked (none = fully locked).
                dpm.setLockTaskFeatures(
                    admin,
                    DevicePolicyManager.LOCK_TASK_FEATURE_HOME or
                        DevicePolicyManager.LOCK_TASK_FEATURE_KEYGUARD,
                )
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                // Prevent accidental factory reset / debugging escapes.
                dpm.addUserRestriction(admin, "no_safe_boot")
                dpm.addUserRestriction(admin, "no_factory_reset")
                dpm.setStatusBarDisabled(admin, true)
                dpm.setKeyguardDisabled(admin, true)
            }
        } catch (e: Exception) {
            Log.w(TAG, "applyDeviceOwnerPolicies failed", e)
        }
    }

    /** Make this app the default HOME so it relaunches on boot / back-to-home presses. */
    fun setAsPreferredHome() {
        if (!isDeviceOwner()) return
        val filter = IntentFilter(Intent.ACTION_MAIN).apply {
            addCategory(Intent.CATEGORY_HOME)
            addCategory(Intent.CATEGORY_DEFAULT)
        }
        val activity = ComponentName(appContext, "com.adm.kiosk.ui.kiosk.KioskActivity")
        try {
            dpm.addPersistentPreferredActivity(admin, filter, activity)
        } catch (e: Exception) {
            Log.w(TAG, "setAsPreferredHome failed", e)
        }
    }

    fun clearPreferredHome() {
        if (!isDeviceOwner()) return
        try {
            dpm.clearPackagePersistentPreferredActivities(admin, appContext.packageName)
        } catch (e: Exception) {
            Log.w(TAG, "clearPreferredHome failed", e)
        }
    }

    /**
     * Fully release the device from kiosk control for maintenance. Only invoked from the
     * PIN-protected admin area.
     */
    fun releaseDeviceOwnerPolicies() {
        if (!isDeviceOwner()) return
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                dpm.setStatusBarDisabled(admin, false)
                dpm.setKeyguardDisabled(admin, false)
                dpm.clearUserRestriction(admin, "no_safe_boot")
                dpm.clearUserRestriction(admin, "no_factory_reset")
            }
            clearPreferredHome()
            dpm.setLockTaskPackages(admin, arrayOf())
        } catch (e: Exception) {
            Log.w(TAG, "releaseDeviceOwnerPolicies failed", e)
        }
    }

    /**
     * Enter lock task for the given activity. Returns true if a lock was started.
     */
    fun startLockTask(activity: Activity): Boolean {
        return try {
            if (isDeviceOwner()) configureLockTaskPackages()
            activity.startLockTask()
            true
        } catch (e: Exception) {
            Log.w(TAG, "startLockTask failed", e)
            false
        }
    }

    /** Reinicia o televisor (apenas Device Owner, Android 7+). */
    fun reboot(): Boolean {
        if (!isDeviceOwner() || Build.VERSION.SDK_INT < Build.VERSION_CODES.N) return false
        return try {
            dpm.reboot(admin)
            true
        } catch (e: Exception) {
            Log.w(TAG, "reboot failed", e)
            false
        }
    }

    fun stopLockTask(activity: Activity) {
        try {
            activity.stopLockTask()
        } catch (e: Exception) {
            Log.w(TAG, "stopLockTask failed", e)
        }
    }

    companion object {
        private const val TAG = "KioskManager"
    }
}
