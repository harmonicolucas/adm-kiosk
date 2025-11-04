package com.adm.kiosk.ui.admin

import android.app.Activity
import android.app.Application
import android.content.Intent
import android.os.SystemClock
import android.provider.Settings
import com.adm.kiosk.util.HomeLauncher
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.adm.kiosk.data.LinkRepository
import com.adm.kiosk.data.db.WebLink
import com.adm.kiosk.data.settings.KioskSettings
import com.adm.kiosk.data.settings.SettingsRepository
import com.adm.kiosk.kiosk.KioskManager
import com.adm.kiosk.remote.AgentStatus
import com.adm.kiosk.remote.RemoteAgent
import com.adm.kiosk.util.NetworkMonitor
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

data class AuthState(
    val authenticated: Boolean = false,
    val error: String? = null,
    val lockedUntilMs: Long = 0L,
    val remainingAttempts: Int = MAX_ATTEMPTS,
) {
    val isLockedOut: Boolean get() = SystemClock.elapsedRealtime() < lockedUntilMs

    companion object {
        const val MAX_ATTEMPTS = 5
    }
}

class AdminViewModel(app: Application) : AndroidViewModel(app) {

    private val links = LinkRepository.get(app)
    private val settingsRepo = SettingsRepository.get(app)
    private val kioskManager = KioskManager(app)
    private val network = NetworkMonitor(app)

    private val _auth = MutableStateFlow(AuthState())
    val auth: StateFlow<AuthState> = _auth.asStateFlow()

    val linksFlow: StateFlow<List<WebLink>> =
        links.observeAll().stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val settingsFlow: StateFlow<KioskSettings> =
        settingsRepo.settings.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), KioskSettings())

    private var failedAttempts = 0

    fun isDeviceOwner(): Boolean = kioskManager.isDeviceOwner()

    fun submitPin(pin: String) {
        val state = _auth.value
        if (state.isLockedOut) {
            _auth.value = state.copy(error = "Bloqueado. Aguarde antes de tentar novamente.")
            return
        }
        viewModelScope.launch {
            if (settingsRepo.verifyPin(pin)) {
                failedAttempts = 0
                _auth.value = AuthState(authenticated = true)
            } else {
                failedAttempts++
                val remaining = AuthState.MAX_ATTEMPTS - failedAttempts
                if (remaining <= 0) {
                    // Exponential-ish lockout: 30s after exhausting attempts.
                    _auth.value = AuthState(
                        authenticated = false,
                        error = "Demasiadas tentativas. Bloqueado 30s.",
                        lockedUntilMs = SystemClock.elapsedRealtime() + 30_000L,
                        remainingAttempts = 0,
                    )
                    failedAttempts = 0
                } else {
                    _auth.value = state.copy(
                        error = "Código incorreto ($remaining tentativas restantes)",
                        remainingAttempts = remaining,
                    )
                }
            }
        }
    }

    fun lock() {
        _auth.value = AuthState()
    }

    // ---- Link management ----

    fun addOrUpdate(link: WebLink) {
        viewModelScope.launch {
            if (link.id == 0L) {
                val pos = links.count()
                links.add(link.copy(position = pos))
            } else {
                links.update(link)
            }
        }
    }

    fun delete(link: WebLink) {
        viewModelScope.launch { links.delete(link) }
    }

    fun selectAsHome(link: WebLink) {
        viewModelScope.launch {
            settingsRepo.setSelectedLink(link.id)
            settingsRepo.clearRemoteUrl()
        }
    }

    /** Seleciona o link e só depois executa [onDone] (garante persistência antes de sair). */
    fun openLink(link: WebLink, onDone: () -> Unit) {
        viewModelScope.launch {
            settingsRepo.setSelectedLink(link.id)
            settingsRepo.clearRemoteUrl()
            onDone()
        }
    }

    // ---- Gestão remota ----

    val remoteStatus: StateFlow<AgentStatus> = RemoteAgent.status

    fun deviceId(): String = RemoteAgent.deviceId()

    fun setRemoteEnabled(enabled: Boolean) = viewModelScope.launch {
        settingsRepo.setRemoteEnabled(enabled)
        RemoteAgent.rediscover()
    }

    fun setServerUrl(url: String) = viewModelScope.launch {
        settingsRepo.setServerUrl(url)
        RemoteAgent.rediscover()
    }

    fun rediscoverServer() = RemoteAgent.rediscover()

    // ---- Settings ----

    fun setRefreshInterval(seconds: Int) = viewModelScope.launch { settingsRepo.setRefreshInterval(seconds) }
    fun setZoom(percent: Int) = viewModelScope.launch { settingsRepo.setZoom(percent) }
    fun setReloadOnError(enabled: Boolean) = viewModelScope.launch { settingsRepo.setReloadOnError(enabled) }
    fun setRetryDelay(seconds: Int) = viewModelScope.launch { settingsRepo.setRetryDelay(seconds) }
    fun setKioskEnabled(enabled: Boolean) = viewModelScope.launch { settingsRepo.setKioskModeEnabled(enabled) }
    fun setAutoScroll(enabled: Boolean) = viewModelScope.launch { settingsRepo.setAutoScrollEnabled(enabled) }
    fun setAutoScrollSeconds(seconds: Int) = viewModelScope.launch { settingsRepo.setAutoScrollSeconds(seconds) }

    fun changePin(current: String, newPin: String, onResult: (Boolean, String?) -> Unit) {
        viewModelScope.launch {
            if (!settingsRepo.verifyPin(current)) {
                onResult(false, "Código atual incorreto")
                return@launch
            }
            if (newPin.length != 4 || newPin.any { !it.isDigit() }) {
                onResult(false, "O novo código deve ter 4 dígitos")
                return@launch
            }
            settingsRepo.setPin(newPin)
            onResult(true, null)
        }
    }

    fun testConnection(onResult: (Boolean) -> Unit) {
        onResult(network.isOnline())
    }

    /** Verifica o código de acesso (usado, por ex., para confirmar a saída do Kiosk). */
    fun checkPin(pin: String, onResult: (Boolean) -> Unit) {
        viewModelScope.launch { onResult(settingsRepo.verifyPin(pin)) }
    }

    /**
     * Exit kiosk for maintenance: stop lock task, release device-owner policies,
     * keep kiosk disabled and send the user to the Android home/menu.
     */
    fun exitKiosk(activity: Activity, disableKiosk: Boolean, onDone: () -> Unit) {
        viewModelScope.launch {
            if (disableKiosk) settingsRepo.setKioskModeEnabled(false)
            kioskManager.stopLockTask(activity)
            if (kioskManager.isDeviceOwner()) {
                kioskManager.releaseDeviceOwnerPolicies()
            }
            // Ir para o ambiente Android. Sendo esta app o launcher, HOME voltaria a abri-la,
            // por isso nesse caso abre-se as Definições do Android.
            val target = if (HomeLauncher.isDefaultHome(activity)) {
                Intent(Settings.ACTION_SETTINGS)
            } else {
                Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME)
            }
            try {
                activity.startActivity(target.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            } catch (_: Exception) {
                // Sem destino disponível: apenas fechamos.
            }
            onDone()
        }
    }
}
