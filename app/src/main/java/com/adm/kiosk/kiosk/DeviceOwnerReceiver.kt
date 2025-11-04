package com.adm.kiosk.kiosk

import android.app.admin.DeviceAdminReceiver
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.widget.Toast

/**
 * Device admin / device owner callback receiver.
 *
 * When the app is provisioned as Device Owner (see README), this component allows the app
 * to configure a real Lock Task (Kiosk) whitelist and lock itself to the foreground.
 */
class DeviceOwnerReceiver : DeviceAdminReceiver() {

    override fun onEnabled(context: Context, intent: Intent) {
        super.onEnabled(context, intent)
        Toast.makeText(context, "Kiosk TV: administrador de dispositivo ativo", Toast.LENGTH_SHORT).show()
    }

    override fun onProfileProvisioningComplete(context: Context, intent: Intent) {
        super.onProfileProvisioningComplete(context, intent)
        // Configure lock task packages immediately after provisioning.
        KioskManager(context).configureLockTaskPackages()
    }

    override fun onDisabled(context: Context, intent: Intent) {
        super.onDisabled(context, intent)
        Toast.makeText(context, "Kiosk TV: administrador de dispositivo desativado", Toast.LENGTH_SHORT).show()
    }

    companion object {
        fun componentName(context: Context): ComponentName =
            ComponentName(context.applicationContext, DeviceOwnerReceiver::class.java)
    }
}
