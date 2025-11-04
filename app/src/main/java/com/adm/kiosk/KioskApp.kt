package com.adm.kiosk

import android.app.Application
import com.adm.kiosk.data.settings.SettingsRepository
import com.adm.kiosk.remote.RemoteAgent
import com.adm.kiosk.util.NetworkMonitor
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

class KioskApp : Application() {

    val appScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    /** Mantém a referência: se o monitor for recolhido, o Android larga a rede local. */
    private var networkMonitor: NetworkMonitor? = null

    override fun onCreate() {
        super.onCreate()
        // Rede local sem Internet: o WebView e o agente usam a LAN na mesma.
        networkMonitor = NetworkMonitor(this).also { it.holdLan() }
        // Guarantee an administration PIN exists on first launch.
        appScope.launch {
            SettingsRepository.get(this@KioskApp).ensurePin(DEFAULT_PIN)
        }
        RemoteAgent.start(this, appScope)
    }

    companion object {
        /** Default administration code on a fresh install. Change it in the admin area. */
        const val DEFAULT_PIN = "0000"
    }
}
