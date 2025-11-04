package com.adm.kiosk.ui.kiosk

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.adm.kiosk.data.LinkRepository
import com.adm.kiosk.data.db.WebLink
import com.adm.kiosk.data.settings.KioskSettings
import com.adm.kiosk.data.settings.SettingsRepository
import com.adm.kiosk.util.NetworkMonitor
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn

data class KioskUiState(
    val loading: Boolean = true,
    val link: WebLink? = null,
    val settings: KioskSettings = KioskSettings(),
    val online: Boolean = true,
    val noLinks: Boolean = false,
)

class KioskViewModel(app: Application) : AndroidViewModel(app) {

    private val links = LinkRepository.get(app)
    private val settingsRepo = SettingsRepository.get(app)
    private val network = NetworkMonitor(app)

    /**
     * Página a apresentar: o URL definido pelo servidor central tem prioridade; caso
     * contrário, o link selecionado localmente (ou o primeiro da lista).
     */
    val state: StateFlow<KioskUiState> =
        combine(
            settingsRepo.settings,
            links.observeAll(),
            network.online,
        ) { settings, all, online ->
            val remote = settings.remoteUrl.takeIf { it.isNotBlank() }?.let {
                WebLink(id = REMOTE_LINK_ID, name = settings.deviceName.ifBlank { "Remoto" }, url = it)
            }
            val link = remote
                ?: all.firstOrNull { it.id == settings.selectedLinkId }
                ?: all.firstOrNull()
            KioskUiState(
                loading = false,
                link = link,
                settings = settings,
                online = online,
                noLinks = link == null,
            )
        }.stateIn(
            scope = viewModelScope,
            started = SharingStarted.WhileSubscribed(5_000),
            initialValue = KioskUiState(),
        )

    val onlineState: StateFlow<Boolean> =
        network.online.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), true)

    /** Estado imediato da ligação (link up/down). */
    fun isConnectedNow(): Boolean = network.isConnected()

    /** Estado imediato de Internet validada. */
    fun isInternetValidated(): Boolean = network.isOnline()

    companion object {
        const val REMOTE_LINK_ID = -100L
    }
}
