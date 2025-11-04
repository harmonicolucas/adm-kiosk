package com.adm.kiosk.data.settings

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.longPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.adm.kiosk.security.PinCrypto
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "kiosk_settings")

/**
 * Immutable snapshot of user configurable settings.
 */
data class KioskSettings(
    val selectedLinkId: Long = -1L,
    val refreshIntervalSeconds: Int = 0,   // 0 = disabled
    val zoomPercent: Int = 100,            // 100 = no zoom
    val reloadOnError: Boolean = true,
    val retryDelaySeconds: Int = 10,
    val keepScreenOn: Boolean = true,
    val kioskModeEnabled: Boolean = true,
    val pinConfigured: Boolean = false,
    /** Rotate through cut-off content (hidden flights) automatically. */
    val autoScrollEnabled: Boolean = true,
    val autoScrollSeconds: Int = 10,
    /** The "set as launcher" prompt was already shown once at startup. */
    val homePromptShown: Boolean = false,

    // ---- Gestão remota (servidor central de administração) ----
    val remoteEnabled: Boolean = true,
    /** Endereço do servidor (ex.: http://10.0.0.5:8080). Vazio = descoberta automática na rede. */
    val serverUrl: String = "",
    val deviceName: String = "",
    /** DPT (doméstico) / IPT (internacional). */
    val terminal: String = "",
    /** FIDS_DEP / FIDS_ARR / GATE. */
    val screenType: String = "",
    val gate: String = "",
    /** URL definido pelo servidor; quando preenchido tem prioridade sobre os links locais. */
    val remoteUrl: String = "",
    val remoteConfigVersion: Int = 0,
)

/** Configuração enviada pelo servidor central. */
data class RemoteConfig(
    val version: Int,
    val name: String,
    val terminal: String,
    val screenType: String,
    val gate: String,
    val url: String,
    val zoomPercent: Int,
    val refreshSeconds: Int,
    val autoScroll: Boolean,
    val autoScrollSeconds: Int,
    val kioskEnabled: Boolean,
    val reloadOnError: Boolean,
    val retryDelaySeconds: Int,
)

class SettingsRepository private constructor(private val context: Context) {

    private object Keys {
        val SELECTED_LINK = longPreferencesKey("selected_link_id")
        val REFRESH = intPreferencesKey("refresh_interval_seconds")
        val ZOOM = intPreferencesKey("zoom_percent")
        val RELOAD_ON_ERROR = booleanPreferencesKey("reload_on_error")
        val RETRY_DELAY = intPreferencesKey("retry_delay_seconds")
        val KEEP_SCREEN_ON = booleanPreferencesKey("keep_screen_on")
        val KIOSK_ENABLED = booleanPreferencesKey("kiosk_mode_enabled")
        val PIN_HASH = stringPreferencesKey("pin_hash")
        val PIN_SALT = stringPreferencesKey("pin_salt")
        val AUTO_SCROLL = booleanPreferencesKey("auto_scroll_enabled")
        val AUTO_SCROLL_SECONDS = intPreferencesKey("auto_scroll_seconds")
        val HOME_PROMPT_SHOWN = booleanPreferencesKey("home_prompt_shown")
        val REMOTE_ENABLED = booleanPreferencesKey("remote_enabled")
        val SERVER_URL = stringPreferencesKey("server_url")
        val DEVICE_NAME = stringPreferencesKey("device_name")
        val TERMINAL = stringPreferencesKey("terminal")
        val SCREEN_TYPE = stringPreferencesKey("screen_type")
        val GATE = stringPreferencesKey("gate")
        val REMOTE_URL = stringPreferencesKey("remote_url")
        val REMOTE_CONFIG_VERSION = intPreferencesKey("remote_config_version")
    }

    val settings: Flow<KioskSettings> = context.dataStore.data.map { p ->
        KioskSettings(
            selectedLinkId = p[Keys.SELECTED_LINK] ?: -1L,
            refreshIntervalSeconds = p[Keys.REFRESH] ?: 0,
            zoomPercent = p[Keys.ZOOM] ?: 100,
            reloadOnError = p[Keys.RELOAD_ON_ERROR] ?: true,
            retryDelaySeconds = p[Keys.RETRY_DELAY] ?: 10,
            keepScreenOn = p[Keys.KEEP_SCREEN_ON] ?: true,
            kioskModeEnabled = p[Keys.KIOSK_ENABLED] ?: true,
            pinConfigured = p.contains(Keys.PIN_HASH),
            autoScrollEnabled = p[Keys.AUTO_SCROLL] ?: true,
            autoScrollSeconds = p[Keys.AUTO_SCROLL_SECONDS] ?: 10,
            homePromptShown = p[Keys.HOME_PROMPT_SHOWN] ?: false,
            remoteEnabled = p[Keys.REMOTE_ENABLED] ?: true,
            serverUrl = p[Keys.SERVER_URL] ?: "",
            deviceName = p[Keys.DEVICE_NAME] ?: "",
            terminal = p[Keys.TERMINAL] ?: "",
            screenType = p[Keys.SCREEN_TYPE] ?: "",
            gate = p[Keys.GATE] ?: "",
            remoteUrl = p[Keys.REMOTE_URL] ?: "",
            remoteConfigVersion = p[Keys.REMOTE_CONFIG_VERSION] ?: 0,
        )
    }

    suspend fun current(): KioskSettings = settings.first()

    suspend fun setSelectedLink(id: Long) = context.dataStore.edit { it[Keys.SELECTED_LINK] = id }

    suspend fun setRefreshInterval(seconds: Int) =
        context.dataStore.edit { it[Keys.REFRESH] = seconds.coerceAtLeast(0) }

    suspend fun setZoom(percent: Int) =
        context.dataStore.edit { it[Keys.ZOOM] = percent.coerceIn(25, 400) }

    suspend fun setReloadOnError(enabled: Boolean) =
        context.dataStore.edit { it[Keys.RELOAD_ON_ERROR] = enabled }

    suspend fun setRetryDelay(seconds: Int) =
        context.dataStore.edit { it[Keys.RETRY_DELAY] = seconds.coerceIn(3, 300) }

    suspend fun setKeepScreenOn(enabled: Boolean) =
        context.dataStore.edit { it[Keys.KEEP_SCREEN_ON] = enabled }

    suspend fun setKioskModeEnabled(enabled: Boolean) =
        context.dataStore.edit { it[Keys.KIOSK_ENABLED] = enabled }

    suspend fun setAutoScrollEnabled(enabled: Boolean) =
        context.dataStore.edit { it[Keys.AUTO_SCROLL] = enabled }

    suspend fun setAutoScrollSeconds(seconds: Int) =
        context.dataStore.edit { it[Keys.AUTO_SCROLL_SECONDS] = seconds.coerceIn(3, 300) }

    suspend fun setHomePromptShown() =
        context.dataStore.edit { it[Keys.HOME_PROMPT_SHOWN] = true }

    suspend fun setRemoteEnabled(enabled: Boolean) =
        context.dataStore.edit { it[Keys.REMOTE_ENABLED] = enabled }

    suspend fun setServerUrl(url: String) =
        context.dataStore.edit { it[Keys.SERVER_URL] = url.trim().trimEnd('/') }

    /** A escolha manual de um link no televisor sobrepõe-se ao URL remoto. */
    suspend fun clearRemoteUrl() =
        context.dataStore.edit { it[Keys.REMOTE_URL] = "" }

    suspend fun applyRemoteConfig(c: RemoteConfig) = context.dataStore.edit {
        it[Keys.REMOTE_CONFIG_VERSION] = c.version
        it[Keys.DEVICE_NAME] = c.name
        it[Keys.TERMINAL] = c.terminal
        it[Keys.SCREEN_TYPE] = c.screenType
        it[Keys.GATE] = c.gate
        it[Keys.REMOTE_URL] = c.url.trim()
        it[Keys.ZOOM] = c.zoomPercent.coerceIn(25, 400)
        it[Keys.REFRESH] = c.refreshSeconds.coerceAtLeast(0)
        it[Keys.AUTO_SCROLL] = c.autoScroll
        it[Keys.AUTO_SCROLL_SECONDS] = c.autoScrollSeconds.coerceIn(3, 300)
        it[Keys.KIOSK_ENABLED] = c.kioskEnabled
        it[Keys.RELOAD_ON_ERROR] = c.reloadOnError
        it[Keys.RETRY_DELAY] = c.retryDelaySeconds.coerceIn(3, 300)
    }

    // ------- PIN management (salted hash, never stored in clear) -------

    /** Ensures a PIN exists; if not, sets the provided default. */
    suspend fun ensurePin(defaultPin: String) {
        val prefs = context.dataStore.data.first()
        if (!prefs.contains(Keys.PIN_HASH)) {
            setPin(defaultPin)
        }
    }

    suspend fun setPin(pin: String) {
        val salt = PinCrypto.newSalt()
        val hash = PinCrypto.hash(pin, salt)
        context.dataStore.edit {
            it[Keys.PIN_SALT] = salt
            it[Keys.PIN_HASH] = hash
        }
    }

    suspend fun verifyPin(pin: String): Boolean {
        val prefs = context.dataStore.data.first()
        val salt = prefs[Keys.PIN_SALT] ?: return false
        val hash = prefs[Keys.PIN_HASH] ?: return false
        return PinCrypto.verify(pin, salt, hash)
    }

    companion object {
        @Volatile
        private var INSTANCE: SettingsRepository? = null

        fun get(context: Context): SettingsRepository =
            INSTANCE ?: synchronized(this) {
                INSTANCE ?: SettingsRepository(context.applicationContext).also { INSTANCE = it }
            }
    }
}
