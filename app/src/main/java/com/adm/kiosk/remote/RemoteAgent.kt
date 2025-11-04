package com.adm.kiosk.remote

import android.content.Context
import android.content.Intent
import android.net.ConnectivityManager
import android.net.wifi.WifiManager
import android.util.Log
import com.adm.kiosk.data.settings.KioskSettings
import com.adm.kiosk.data.settings.RemoteConfig
import com.adm.kiosk.data.settings.SettingsRepository
import com.adm.kiosk.kiosk.KioskManager
import com.adm.kiosk.ui.kiosk.KioskActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.HttpURLConnection
import java.net.Inet4Address
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.SocketTimeoutException
import java.net.URL

/** Comando enviado pelo administrador web para este televisor. */
data class RemoteCommand(val id: Long, val type: String, val payload: JSONObject)

data class AgentStatus(
    val enabled: Boolean = true,
    val server: String = "",
    val connected: Boolean = false,
    val message: String = "A iniciar…",
    val lastContactMs: Long = 0L,
)

/** Estado da página apresentada, reportado ao servidor. */
data class PageReport(
    val url: String = "",
    val state: String = "loading",
    val error: String = "",
)

/**
 * Agente de gestão remota: descobre o servidor central na rede, envia periodicamente os
 * dados do televisor (rede, modelo, página, estado) e aplica a configuração e os comandos
 * definidos no administrador web.
 */
object RemoteAgent {

    private const val TAG = "RemoteAgent"
    const val DISCOVERY_PORT = 47800
    private const val AGENT_PORT = 47801
    private const val DISCOVER_MSG = "ADM-KIOSK-DISCOVER"
    private const val ANNOUNCE_PREFIX = "ADM-KIOSK-ANNOUNCE "
    private const val HEARTBEAT_MS = 10_000L

    /** Comandos que precisam do ecrã de apresentação (recarregar, identificar, captura…). */
    val SCREEN_COMMANDS = setOf("reload", "identify", "screenshot", "clear_cache")

    private val _commands = MutableSharedFlow<RemoteCommand>(extraBufferCapacity = 16)
    val commands: SharedFlow<RemoteCommand> = _commands.asSharedFlow()

    private val _status = MutableStateFlow(AgentStatus())
    val status: StateFlow<AgentStatus> = _status.asStateFlow()

    @Volatile var page = PageReport()

    /** Fornece uma imagem do ecrã (JPEG, largura máxima e qualidade) para a sessão ao vivo. */
    @Volatile var frameProvider: (suspend (Int, Int) -> ByteArray?)? = null

    /** Eventos de controlo remoto (clique, deslocamento, teclas) recebidos durante a sessão ao vivo. */
    private val _inputs = MutableSharedFlow<JSONObject>(extraBufferCapacity = 64)
    val inputs: SharedFlow<JSONObject> = _inputs.asSharedFlow()

    private var liveJob: Job? = null

    private lateinit var appContext: Context
    private lateinit var scope: CoroutineScope
    private var loopJob: Job? = null
    @Volatile private var discovered: String? = null
    @Volatile private var wakeUp = false
    private var multicastLock: WifiManager.MulticastLock? = null

    fun start(context: Context, appScope: CoroutineScope) {
        if (loopJob != null) return
        appContext = context.applicationContext
        scope = appScope
        holdMulticast()
        loopJob = scope.launch(Dispatchers.IO) { loop() }
        scope.launch(Dispatchers.IO) { waitLoop() }
    }

    /**
     * Pedido de espera sempre aberto com o servidor: é respondido logo que o administrador inicia
     * uma sessão ao vivo, envia um comando ou altera a configuração (sem esperar pelo heartbeat).
     */
    private suspend fun waitLoop() {
        var gen = -1L
        while (true) {
            val st = _status.value
            if (!st.enabled || !st.connected || st.server.isBlank()) {
                delay(2000)
                continue
            }
            try {
                val r = postBytes(
                    "${st.server}/api/device/wait?id=${deviceId()}&gen=$gen",
                    ByteArray(0), "application/json", readTimeoutMs = 35_000,
                )
                gen = r.optLong("gen", gen)
                if (r.optBoolean("wake")) wakeUp = true
                r.optJSONObject("live")?.let { if (it.optBoolean("active")) startLive(st.server, it) }
            } catch (e: Exception) {
                Log.w(TAG, "wait failed: ${e.message}")
                delay(3000)
            }
        }
    }

    /** Volta a procurar o servidor na rede no próximo ciclo. */
    fun rediscover() {
        discovered = null
        wakeUp = true
    }

    fun deviceId(): String = DeviceInfo.deviceId(appContext)

    private suspend fun loop() {
        val settingsRepo = SettingsRepository.get(appContext)
        var failures = 0
        var skipConfigured = false
        var seenUrl = ""
        while (true) {
            val s = settingsRepo.current()
            if (s.serverUrl != seenUrl) {
                seenUrl = s.serverUrl
                skipConfigured = false
                failures = 0
            }
            if (!s.remoteEnabled) {
                _status.value = AgentStatus(enabled = false, message = "Gestão remota desativada")
                sleep(HEARTBEAT_MS)
                continue
            }
            val server = if (s.serverUrl.isNotBlank() && !skipConfigured && failures < 2) {
                s.serverUrl
            } else {
                discovered ?: discover() ?: s.serverUrl.ifBlank { null }
            }
            if (server == null) {
                _status.value = _status.value.copy(
                    enabled = true, server = "", connected = false,
                    message = "A procurar o servidor na rede…",
                )
                sleep(15_000)
                continue
            }
            try {
                val response = postJson("$server/api/device/heartbeat", heartbeat(s))
                failures = 0
                if (s.serverUrl.isNotBlank() && server == s.serverUrl) skipConfigured = false
                _status.value = AgentStatus(
                    enabled = true, server = server, connected = true,
                    message = "Ligado ao servidor", lastContactMs = System.currentTimeMillis(),
                )
                handleResponse(server, s, response)
            } catch (e: Exception) {
                failures++
                Log.w(TAG, "heartbeat failed ($failures): ${e.message}")
                _status.value = _status.value.copy(
                    server = server, connected = false,
                    message = "Sem contacto com o servidor ($server)",
                )
                if (failures >= 2) {
                    skipConfigured = true
                    discovered = null
                }
            }
            sleep(HEARTBEAT_MS)
        }
    }

    private suspend fun sleep(ms: Long) {
        var waited = 0L
        while (waited < ms && !wakeUp) {
            delay(200)
            waited += 200
        }
        wakeUp = false
    }

    // ---------------- Descoberta automática (UDP broadcast) ----------------

    private fun holdMulticast() {
        if (multicastLock?.isHeld == true) return
        val wifi = appContext.applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager ?: return
        multicastLock = wifi.createMulticastLock("adm-kiosk").apply {
            setReferenceCounted(false)
            acquire()
        }
    }

    private fun broadcastTargets(): List<String> {
        val out = linkedSetOf<String>()
        val cm = appContext.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        for (network in cm.allNetworks) {
            val lp = cm.getLinkProperties(network) ?: continue
            for (link in lp.linkAddresses) {
                val addr = link.address
                if (addr !is Inet4Address || addr.isLoopbackAddress) continue
                val prefix = link.prefixLength
                if (prefix !in 1..31) continue
                val raw = addr.address
                val ip = ((raw[0].toInt() and 255) shl 24) or ((raw[1].toInt() and 255) shl 16) or
                    ((raw[2].toInt() and 255) shl 8) or (raw[3].toInt() and 255)
                val mask = -1 shl (32 - prefix)
                val bc = ip or mask.inv()
                val text = "${bc ushr 24 and 255}.${bc ushr 16 and 255}.${bc ushr 8 and 255}.${bc and 255}"
                if (!text.startsWith("169.254.")) out.add(text)
            }
        }
        DeviceInfo.network(appContext).broadcast.takeIf { it.isNotBlank() }?.let(out::add)
        out.add("255.255.255.255")
        return out.toList()
    }

    private fun serverFromPacket(text: String): String? {
        val json = if (text.startsWith(ANNOUNCE_PREFIX)) text.removePrefix(ANNOUNCE_PREFIX) else text
        val url = runCatching { JSONObject(json).optString("server") }.getOrNull()?.trimEnd('/') ?: return null
        return url.takeIf { it.startsWith("http") }
    }

    private fun discover(): String? {
        holdMulticast()
        if (broadcastTargets().isEmpty()) return null
        return try {
            DatagramSocket(null).use { socket ->
                socket.reuseAddress = true
                socket.broadcast = true
                try {
                    socket.bind(InetSocketAddress(AGENT_PORT))
                } catch (_: Exception) {
                    socket.bind(InetSocketAddress(0))
                }
                socket.soTimeout = 600
                val msg = DISCOVER_MSG.toByteArray()
                repeat(3) {
                    broadcastTargets().forEach { target ->
                        runCatching {
                            socket.send(DatagramPacket(msg, msg.size, InetAddress.getByName(target), DISCOVERY_PORT))
                        }
                    }
                    val deadline = System.currentTimeMillis() + 1200
                    while (System.currentTimeMillis() < deadline) {
                        val buf = ByteArray(2048)
                        val packet = DatagramPacket(buf, buf.size)
                        try {
                            socket.receive(packet)
                        } catch (_: SocketTimeoutException) {
                            break
                        }
                        val text = String(packet.data, 0, packet.length)
                        val url = serverFromPacket(text)
                        if (url != null) {
                            discovered = url
                            return url
                        }
                    }
                }
                null
            }
        } catch (e: Exception) {
            Log.w(TAG, "discovery failed: ${e.message}")
            null
        }
    }

    // ---------------- Heartbeat ----------------

    private fun heartbeat(s: KioskSettings): JSONObject {
        val p = page
        return JSONObject()
            .put("id", deviceId())
            .put("platform", "android")
            .put("configVersion", s.remoteConfigVersion)
            .put("device", DeviceInfo.device(appContext))
            .put("network", DeviceInfo.network(appContext).toJson())
            .put(
                "state",
                JSONObject().put("url", p.url).put("page", p.state).put("error", p.error),
            )
            .put(
                "settings",
                JSONObject()
                    .put("name", s.deviceName)
                    .put("terminal", s.terminal)
                    .put("screenType", s.screenType)
                    .put("gate", s.gate)
                    .put("url", s.remoteUrl.ifBlank { p.url })
                    .put("zoom", s.zoomPercent)
                    .put("refreshSeconds", s.refreshIntervalSeconds)
                    .put("autoScroll", s.autoScrollEnabled)
                    .put("autoScrollSeconds", s.autoScrollSeconds)
                    .put("kioskEnabled", s.kioskModeEnabled)
                    .put("reloadOnError", s.reloadOnError)
                    .put("retryDelaySeconds", s.retryDelaySeconds),
            )
    }

    // ---------------- Sessão ao vivo (ver e controlar) ----------------

    @Synchronized
    private fun startLive(server: String, initial: JSONObject) {
        if (liveJob?.isActive == true) return
        liveJob = scope.launch(Dispatchers.IO) {
            var live: JSONObject = initial
            var last: ByteArray? = null
            var failures = 0
            var lastBringToFront = 0L
            while (live.optBoolean("active")) {
                val started = System.currentTimeMillis()
                val interval = live.optInt("intervalMs", 100).coerceIn(66, 5000)
                val (width, quality) = when (live.optString("quality")) {
                    "high" -> 1280 to 70
                    "low" -> 720 to 45
                    else -> 960 to 60
                }
                val provider = frameProvider
                // Time limit: a capture started just before the screen is destroyed never answers.
                val frame = if (provider == null) null else runCatching {
                    withTimeoutOrNull(3000) { provider(width, quality) }
                }.getOrNull()
                val status = when {
                    provider == null -> "noscreen"
                    frame == null -> "capture"
                    else -> ""
                }
                if (provider == null && started - lastBringToFront > 10_000) {
                    lastBringToFront = started
                    bringKioskToFront()
                }
                // Ecrã sem alterações: corpo vazio, apenas para recolher os eventos de controlo.
                val same = frame == null || (last != null && frame.contentEquals(last))
                try {
                    val r = postBytes(
                        "$server/api/device/frame?id=${deviceId()}&status=$status",
                        if (same) ByteArray(0) else frame!!, "image/jpeg",
                    )
                    failures = 0
                    if (!same) last = frame
                    live = r.optJSONObject("live") ?: break
                    val inputs = r.optJSONArray("inputs")
                    if (inputs != null) {
                        for (i in 0 until inputs.length()) inputs.optJSONObject(i)?.let { _inputs.emit(it) }
                    }
                } catch (e: Exception) {
                    if (++failures >= 3) break
                    delay(500)
                    continue
                }
                val rest = interval - (System.currentTimeMillis() - started)
                if (rest > 0) delay(rest)
            }
        }
    }

    /** Sem ecrã de apresentação (TV nas definições ou noutra app): volta a abrir o ADM Kiosk. */
    private suspend fun bringKioskToFront() {
        runCatching {
            withContext(Dispatchers.Main) {
                appContext.startActivity(
                    Intent(appContext, KioskActivity::class.java).addFlags(
                        Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT,
                    ),
                )
            }
        }.onFailure { Log.w(TAG, "cannot bring kiosk to front: ${it.message}") }
    }

    private suspend fun handleResponse(server: String, s: KioskSettings, r: JSONObject) {
        r.optJSONObject("live")?.let { live ->
            if (live.optBoolean("active")) startLive(server, live)
        }
        r.optJSONObject("config")?.let { c ->
            val version = c.optInt("version", 0)
            if (version > 0 && version != s.remoteConfigVersion) {
                SettingsRepository.get(appContext).applyRemoteConfig(
                    RemoteConfig(
                        version = version,
                        name = c.optString("name"),
                        terminal = c.optString("terminal"),
                        screenType = c.optString("screenType"),
                        gate = c.optString("gate"),
                        url = c.optString("url"),
                        zoomPercent = c.optInt("zoom", s.zoomPercent),
                        refreshSeconds = c.optInt("refreshSeconds", s.refreshIntervalSeconds),
                        autoScroll = c.optBoolean("autoScroll", s.autoScrollEnabled),
                        autoScrollSeconds = c.optInt("autoScrollSeconds", s.autoScrollSeconds),
                        kioskEnabled = c.optBoolean("kioskEnabled", s.kioskModeEnabled),
                        reloadOnError = c.optBoolean("reloadOnError", s.reloadOnError),
                        retryDelaySeconds = c.optInt("retryDelaySeconds", s.retryDelaySeconds),
                    ),
                )
                Log.i(TAG, "remote config v$version applied")
            }
        }
        val cmds = r.optJSONArray("commands") ?: return
        for (i in 0 until cmds.length()) {
            val o = cmds.optJSONObject(i) ?: continue
            val cmd = RemoteCommand(
                id = o.optLong("id"),
                type = o.optString("type"),
                payload = o.optJSONObject("payload") ?: JSONObject(),
            )
            execute(server, cmd)
        }
    }

    private suspend fun execute(server: String, cmd: RemoteCommand) {
        when (cmd.type) {
            in SCREEN_COMMANDS -> {
                if (_commands.subscriptionCount.value > 0) {
                    _commands.emit(cmd)
                } else {
                    reportResult(cmd.id, false, "Ecrã de apresentação não está ativo")
                }
            }
            "restart_app" -> {
                val ok = runCatching {
                    withContext(Dispatchers.Main) {
                        appContext.startActivity(
                            Intent(appContext, KioskActivity::class.java).addFlags(
                                Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK,
                            ),
                        )
                    }
                }.isSuccess
                reportResult(cmd.id, ok, if (ok) "Aplicação reiniciada" else "Falha ao reiniciar")
            }
            "set_pin" -> {
                val pin = cmd.payload.optString("pin")
                if (pin.length == 4 && pin.all { it.isDigit() }) {
                    SettingsRepository.get(appContext).setPin(pin)
                    reportResult(cmd.id, true, "Código de acesso alterado")
                } else {
                    reportResult(cmd.id, false, "O código deve ter 4 dígitos")
                }
            }
            "reboot" -> {
                val km = KioskManager(appContext)
                if (km.reboot()) {
                    reportResult(cmd.id, true, "A reiniciar o televisor")
                } else {
                    reportResult(cmd.id, false, "Reiniciar exige Device Owner (Android 7+)")
                }
            }
            else -> reportResult(cmd.id, false, "Comando desconhecido: ${cmd.type}")
        }
    }

    // ---------------- Resultados / capturas ----------------

    fun reportResult(commandId: Long, ok: Boolean, message: String) {
        val server = _status.value.server.ifBlank { return }
        scope.launch(Dispatchers.IO) {
            runCatching {
                postJson(
                    "$server/api/device/command-result",
                    JSONObject()
                        .put("id", deviceId())
                        .put("commandId", commandId)
                        .put("ok", ok)
                        .put("message", message),
                )
            }.onFailure { Log.w(TAG, "result upload failed: ${it.message}") }
        }
    }

    fun uploadScreenshot(commandId: Long, jpeg: ByteArray) {
        val server = _status.value.server.ifBlank { return }
        scope.launch(Dispatchers.IO) {
            runCatching {
                postBytes("$server/api/device/screenshot?id=${deviceId()}&cmd=$commandId", jpeg, "image/jpeg")
            }.onFailure { Log.w(TAG, "screenshot upload failed: ${it.message}") }
        }
    }

    private fun postJson(url: String, body: JSONObject): JSONObject =
        postBytes(url, body.toString().toByteArray(Charsets.UTF_8), "application/json; charset=utf-8")

    private fun postBytes(
        url: String,
        bytes: ByteArray,
        contentType: String,
        readTimeoutMs: Int = 15_000,
    ): JSONObject {
        val conn = URL(url).openConnection() as HttpURLConnection
        try {
            conn.requestMethod = "POST"
            conn.connectTimeout = 5000
            conn.readTimeout = readTimeoutMs
            conn.doOutput = true
            conn.setRequestProperty("Content-Type", contentType)
            conn.setFixedLengthStreamingMode(bytes.size)
            conn.outputStream.use { it.write(bytes) }
            val code = conn.responseCode
            if (code !in 200..299) throw IllegalStateException("HTTP $code")
            val out = ByteArrayOutputStream()
            conn.inputStream.use { it.copyTo(out) }
            val text = out.toString("UTF-8")
            // Sem disconnect(): a ligação fica reutilizável (keep-alive) para as imagens seguintes.
            return if (text.isBlank()) JSONObject() else JSONObject(text)
        } catch (e: Exception) {
            conn.disconnect()
            throw e
        }
    }
}
