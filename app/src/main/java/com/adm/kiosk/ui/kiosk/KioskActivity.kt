package com.adm.kiosk.ui.kiosk

import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.InputDevice
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.PixelCopy
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.webkit.WebView
import android.widget.FrameLayout
import androidx.activity.ComponentActivity
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.ui.Modifier
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.ComposeView
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.adm.kiosk.data.settings.KioskSettings
import com.adm.kiosk.data.settings.SettingsRepository
import com.adm.kiosk.kiosk.KioskManager
import com.adm.kiosk.remote.DeviceInfo
import com.adm.kiosk.remote.PageReport
import com.adm.kiosk.remote.RemoteAgent
import com.adm.kiosk.remote.RemoteCommand
import com.adm.kiosk.remote.ScreenRemote
import com.adm.kiosk.ui.admin.AdminActivity
import com.adm.kiosk.ui.theme.AdmKioskTheme
import com.adm.kiosk.util.DeviceType
import com.adm.kiosk.util.HomeLauncher
import com.adm.kiosk.web.KioskWebListener
import com.adm.kiosk.web.WebViewFactory
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import kotlin.coroutines.resume

/**
 * Full-screen dedicated browser (digital signage) running in kiosk / lock-task mode.
 * Registered as the Android HOME launcher.
 */
class KioskActivity : ComponentActivity() {

    private lateinit var root: FrameLayout
    private var webView: WebView? = null
    private lateinit var overlayHost: ComposeView

    private val vm: KioskViewModel by lazy {
        androidx.lifecycle.ViewModelProvider(this)[KioskViewModel::class.java]
    }
    private lateinit var kioskManager: KioskManager
    private lateinit var settingsRepo: SettingsRepository

    private var refreshJob: Job? = null
    private var retryJob: Job? = null
    private var rotateJob: Job? = null
    private var refreshSeconds = -1
    private var rotateConfig: Pair<Boolean, Int>? = null

    private var overlay by mutableStateOf(OverlayState.Splash)
    private var identifyText by mutableStateOf<String?>(null)
    private var currentUrl: String? = null
    private var currentZoom = 100
    private var hasError = false
    private var firstLoadDone = false

    // Multi-press BACK to reach the (PIN protected) admin area from any remote.
    private var backPressTimes = ArrayDeque<Long>()
    private val tapTimes = ArrayDeque<Long>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        kioskManager = KioskManager(this)
        settingsRepo = SettingsRepository.get(this)

        WindowCompat.setDecorFitsSystemWindows(window, false)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        root = FrameLayout(this).apply {
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT,
            )
            setBackgroundColor(android.graphics.Color.WHITE)
        }

        overlayHost = ComposeView(this).apply {
            setContent {
                AdmKioskTheme {
                    Box(Modifier.fillMaxSize()) {
                        KioskOverlay(
                            state = this@KioskActivity.overlay,
                            onOpenAdmin = ::openAdmin,
                        )
                        identifyText?.let { IdentifyBanner(it) }
                    }
                }
            }
        }
        root.addView(overlayHost)
        setContentView(root)

        observeState()
        // Commands must keep arriving while the admin screen covers this activity.
        lifecycleScope.launch {
            RemoteAgent.commands.collect { handleRemoteCommand(it) }
        }
        lifecycleScope.launch {
            RemoteAgent.inputs.collect { handleRemoteInput(it) }
        }
        RemoteAgent.frameProvider = frameProvider
    }

    private val frameProvider: suspend (Int, Int) -> ByteArray? = { maxWidth, quality ->
        withContext(Dispatchers.Main) {
            suspendCancellableCoroutine { cont ->
                captureScreen(maxWidth = maxWidth, quality = quality) { if (cont.isActive) cont.resume(it) }
            }
        }
    }

    /** Início do toque em curso (premir/mover/largar vindos do rato do administrador); 0 = nenhum. */
    private var touchDownAt = 0L

    private fun touch(view: View, action: Int, x: Float, y: Float) {
        val now = SystemClock.uptimeMillis()
        if (action == MotionEvent.ACTION_DOWN) touchDownAt = now
        if (touchDownAt == 0L) return
        val ev = MotionEvent.obtain(touchDownAt, now, action, x, y, 0)
        ev.source = InputDevice.SOURCE_TOUCHSCREEN
        view.dispatchTouchEvent(ev)
        ev.recycle()
        if (action == MotionEvent.ACTION_UP) touchDownAt = 0L
    }

    /** Controlo remoto (sessão ao vivo): cliques, deslocamento e teclas na página apresentada. */
    private fun handleRemoteInput(ev: JSONObject) {
        // Com a administração aberta por cima, é ela que recebe o controlo remoto.
        if (!lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) return
        if (ev.optString("type") == "key" && ev.optString("key") == "Back") {
            registerExitPress()
            return
        }
        val wv = webView ?: return
        val x = ev.optDouble("x", 0.5).toFloat() * wv.width
        val y = ev.optDouble("y", 0.5).toFloat() * wv.height
        when (ev.optString("type")) {
            "click", "rightclick" -> tap(wv, x, y)
            "dblclick" -> { tap(wv, x, y); tap(wv, x, y) }
            "down" -> touch(wv, MotionEvent.ACTION_DOWN, x, y)
            "move" -> touch(wv, MotionEvent.ACTION_MOVE, x, y)
            "up" -> touch(wv, MotionEvent.ACTION_UP, x, y)
            "scroll" -> {
                val dy = ev.optInt("dy", 1) * 120
                wv.evaluateJavascript(
                    "(function(x,y,d){var el=document.elementFromPoint(x*innerWidth,y*innerHeight);" +
                        "while(el&&el!==document.body){var s=getComputedStyle(el).overflowY;" +
                        "if((s=='auto'||s=='scroll')&&el.scrollHeight>el.clientHeight){el.scrollBy(0,d);return;}" +
                        "el=el.parentElement;}window.scrollBy(0,d);})" +
                        "(${ev.optDouble("x", 0.5)},${ev.optDouble("y", 0.5)},$dy)",
                    null,
                )
            }
            "text" -> wv.evaluateJavascript(
                "document.execCommand('insertText',false,${JSONObject.quote(ev.optString("text"))})",
                null,
            )
            "key" -> {
                val name = ev.optString("key")
                if (name == "F5") {
                    recoverPage()
                    return
                }
                val code = ScreenRemote.KEYS[name]
                if (code != null) {
                    wv.dispatchKeyEvent(KeyEvent(KeyEvent.ACTION_DOWN, code))
                    wv.dispatchKeyEvent(KeyEvent(KeyEvent.ACTION_UP, code))
                } else if (name.length == 1) {
                    wv.evaluateJavascript(
                        "document.execCommand('insertText',false,${JSONObject.quote(name)})",
                        null,
                    )
                }
            }
        }
    }

    private fun tap(view: View, x: Float, y: Float) {
        val t = SystemClock.uptimeMillis()
        val down = MotionEvent.obtain(t, t, MotionEvent.ACTION_DOWN, x, y, 0)
        val up = MotionEvent.obtain(t, t + 60, MotionEvent.ACTION_UP, x, y, 0)
        down.source = InputDevice.SOURCE_TOUCHSCREEN
        up.source = InputDevice.SOURCE_TOUCHSCREEN
        view.dispatchTouchEvent(down)
        view.dispatchTouchEvent(up)
        down.recycle()
        up.recycle()
    }

    // ---- Gestão remota ----

    private fun report(state: String, error: String = "") {
        RemoteAgent.page = PageReport(url = currentUrl.orEmpty(), state = state, error = error)
    }

    private fun handleRemoteCommand(cmd: RemoteCommand) {
        when (cmd.type) {
            "reload" -> {
                if (webView == null) {
                    RemoteAgent.reportResult(cmd.id, false, "Nenhuma página configurada")
                } else {
                    recoverPage()
                    RemoteAgent.reportResult(cmd.id, true, "Página recarregada")
                }
            }
            "clear_cache" -> {
                webView?.clearCache(true)
                recoverPage()
                RemoteAgent.reportResult(cmd.id, true, "Cache limpa e página recarregada")
            }
            "identify" -> {
                val seconds = cmd.payload.optInt("seconds", 20).coerceIn(5, 120)
                lifecycleScope.launch {
                    val s = settingsRepo.current()
                    val net = DeviceInfo.network(this@KioskActivity)
                    identifyText = buildString {
                        appendLine(s.deviceName.ifBlank { "Televisor sem nome" })
                        val kind = listOf(terminalLabel(s.terminal), screenTypeLabel(s.screenType))
                            .filter { it.isNotBlank() }.joinToString(" - ")
                        if (kind.isNotBlank()) appendLine(kind + if (s.gate.isNotBlank()) " ${s.gate}" else "")
                        appendLine("IP ${net.ip.ifBlank { "-" }}   Gateway ${net.gateway.ifBlank { "-" }}")
                        append("ID ${RemoteAgent.deviceId().takeLast(8).uppercase()}")
                    }
                    RemoteAgent.reportResult(cmd.id, true, "Identificação mostrada ${seconds}s")
                    delay(seconds * 1000L)
                    identifyText = null
                }
            }
            "screenshot" -> captureScreen { jpeg ->
                if (jpeg == null) {
                    RemoteAgent.reportResult(cmd.id, false, "Não foi possível capturar o ecrã")
                } else {
                    RemoteAgent.uploadScreenshot(cmd.id, jpeg)
                }
            }
        }
    }

    private fun terminalLabel(t: String) = when (t) {
        "DPT" -> "DPT Doméstico"
        "IPT" -> "IPT Internacional"
        else -> ""
    }

    private fun screenTypeLabel(t: String) = when (t) {
        "FIDS_DEP" -> "FIDS Partidas"
        "FIDS_ARR" -> "FIDS Chegadas"
        "GATE" -> "Gate"
        else -> ""
    }

    private fun captureScreen(maxWidth: Int = 1280, quality: Int = 70, onDone: (ByteArray?) -> Unit) =
        ScreenRemote.capture(this, root, maxWidth, quality, onDone)

    private fun observeState() {
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                launch {
                    vm.state.collectLatest { s ->
                        if (s.loading) return@collectLatest
                        when {
                            s.noLinks -> {
                                overlay = OverlayState.NoLinks
                                teardownWebView()
                                report("nolinks")
                            }
                            s.link != null -> {
                                buildOrUpdateWebView(
                                    url = s.link.url,
                                    zoom = resolveZoom(s.settings.zoomPercent, s.link.zoomPercent),
                                )
                                scheduleAutoRefresh(
                                    resolveRefresh(s.settings.refreshIntervalSeconds, s.link.refreshSeconds),
                                )
                                scheduleRotation(s.settings.autoScrollEnabled, s.settings.autoScrollSeconds)
                            }
                        }
                    }
                }
                // Reage a mudanças de ligação (link up/down): mostra "Offline" ao cair a
                // rede e recarrega a página assim que a rede é restabelecida.
                launch {
                    var wasOnline = vm.onlineState.value
                    vm.onlineState.collectLatest { online ->
                        when {
                            online && (!wasOnline || hasError) -> recoverPage()
                            !online && webView != null -> {
                                overlay = OverlayState.Offline
                                report("offline")
                            }
                        }
                        wasOnline = online
                    }
                }
                // Vigia de segurança: mesmo que um evento de rede se perca, verifica
                // periodicamente e recarrega quando a ligação volta (link ou Internet).
                launch {
                    var lastConnected = vm.isConnectedNow()
                    var lastValidated = vm.isInternetValidated()
                    while (true) {
                        delay(10_000)
                        val connected = vm.isConnectedNow()
                        val validated = vm.isInternetValidated()
                        val restored = (connected && !lastConnected) || (validated && !lastValidated)
                        when {
                            restored && webView != null -> recoverPage()
                            hasError && retryJob?.isActive != true -> scheduleRetry()
                            !connected && webView != null && overlay != OverlayState.Offline ->
                                overlay = OverlayState.Offline
                        }
                        lastConnected = connected
                        lastValidated = validated
                    }
                }
            }
        }
    }

    private fun resolveZoom(global: Int, perLink: Int): Int =
        if (perLink > 0) perLink else global

    private fun resolveRefresh(global: Int, perLink: Int): Int =
        if (perLink >= 0) perLink else global

    private fun buildOrUpdateWebView(url: String, zoom: Int) {
        val zoomChanged = zoom != currentZoom
        currentZoom = zoom
        val existing = webView
        if (existing == null) {
            val wv = WebViewFactory.create(
                context = this,
                zoomPercent = { currentZoom },
                listener = object : KioskWebListener {
                    override fun onPageStarted(url: String?) {
                        // Só mostra o splash no 1.º carregamento (evita "flash" a cada refresh).
                        if (!firstLoadDone) overlay = OverlayState.Loading
                        if (!firstLoadDone) report("loading")
                    }

                    override fun onPageFinished(url: String?) {
                        hasError = false
                        firstLoadDone = true
                        retryJob?.cancel()
                        overlay = OverlayState.None
                        report("ok")
                    }

                    override fun onError(isMainFrame: Boolean, description: String?) {
                        if (isMainFrame) {
                            hasError = true
                            overlay = OverlayState.Offline
                            report("error", description.orEmpty())
                            if (retryJob?.isActive != true) scheduleRetry()
                        }
                    }

                    override fun onRendererGone() {
                        val url = currentUrl ?: return
                        teardownWebView()
                        buildOrUpdateWebView(url, currentZoom)
                    }
                },
            )
            root.addView(wv, 0)
            webView = wv
            currentUrl = url
            wv.loadUrl(url)
        } else {
            if (zoomChanged) WebViewFactory.applyZoom(existing, zoom)
            if (currentUrl != url) {
                currentUrl = url
                firstLoadDone = false
                existing.loadUrl(url)
            }
        }
    }

    /** Reloads the configured URL (not the error page) after a failure or network return. */
    private fun recoverPage() {
        val wv = webView ?: return
        val url = currentUrl ?: return
        hasError = false
        overlay = OverlayState.Loading
        wv.loadUrl(url)
    }

    private fun scheduleAutoRefresh(seconds: Int) {
        if (seconds == refreshSeconds && (seconds <= 0 || refreshJob?.isActive == true)) return
        refreshSeconds = seconds
        refreshJob?.cancel()
        if (seconds <= 0) return
        refreshJob = lifecycleScope.launch {
            while (true) {
                delay(seconds * 1000L)
                // Só atualiza se não houver erro e a rede estiver disponível.
                if (!hasError && vm.isConnectedNow()) webView?.reload()
            }
        }
    }

    private fun scheduleRetry() {
        retryJob?.cancel()
        retryJob = lifecycleScope.launch {
            val delaySec = settingsRepo.current().retryDelaySeconds
            while (hasError) {
                delay(delaySec * 1000L)
                // Tenta recarregar sempre que houver ligação de rede ativa.
                if (hasError && vm.isConnectedNow()) {
                    webView?.loadUrl(currentUrl ?: return@launch)
                }
            }
        }
    }

    /**
     * Rotação dos voos cortados: a cada [seconds] avança um ecrã no conteúdo escondido e,
     * no fim, volta ao topo. Não faz nada quando tudo cabe no ecrã.
     */
    private fun scheduleRotation(enabled: Boolean, seconds: Int) {
        val config = enabled to seconds
        if (config == rotateConfig && (!enabled || rotateJob?.isActive == true)) return
        rotateConfig = config
        rotateJob?.cancel()
        if (!enabled) return
        rotateJob = lifecycleScope.launch {
            while (true) {
                delay(seconds.coerceAtLeast(3) * 1000L)
                val wv = webView ?: continue
                if (!hasError && overlay == OverlayState.None) {
                    WebViewFactory.autoScrollStep(wv) { }
                }
            }
        }
    }

    private fun teardownWebView() {
        refreshJob?.cancel()
        refreshSeconds = -1
        webView?.let {
            root.removeView(it)
            it.destroy()
        }
        webView = null
        currentUrl = null
        firstLoadDone = false
    }

    private fun openAdmin() {
        startActivity(Intent(this, AdminActivity::class.java))
    }

    // ---- Kiosk lock + immersive ----

    override fun onResume() {
        super.onResume()
        RemoteAgent.frameProvider = frameProvider
        enterImmersive()
        lifecycleScope.launch {
            val s = settingsRepo.current()
            if (shouldAskToBecomeLauncher(s)) {
                settingsRepo.setHomePromptShown()
                HomeLauncher.requestDefaultHome(this@KioskActivity)
            } else {
                maybeStartLockTask(s)
            }
        }
    }

    /** First start on a TV: ask Android once to make this app the default launcher. */
    private fun shouldAskToBecomeLauncher(s: KioskSettings): Boolean =
        !s.homePromptShown &&
            DeviceType.isTelevision(this) &&
            !kioskManager.isDeviceOwner() &&
            !HomeLauncher.isDefaultHome(this)

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) enterImmersive()
    }

    private fun maybeStartLockTask(s: KioskSettings) {
        // Only engage kiosk (lock task) on TV-class devices or when provisioned as
        // Device Owner. This prevents ordinary phones/tablets from being pinned.
        val kioskAllowed = DeviceType.isTelevision(this) || kioskManager.isDeviceOwner()
        if (s.kioskModeEnabled && kioskAllowed) {
            if (kioskManager.isDeviceOwner()) {
                kioskManager.applyDeviceOwnerPolicies()
            }
            kioskManager.startLockTask(this)
        }
    }

    private fun enterImmersive() {
        val controller = WindowInsetsControllerCompat(window, window.decorView)
        controller.hide(WindowInsetsCompat.Type.systemBars())
        controller.systemBarsBehavior =
            WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) {
            @Suppress("DEPRECATION")
            window.decorView.systemUiVisibility = (
                View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                    or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                    or View.SYSTEM_UI_FLAG_FULLSCREEN
                    or View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                    or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                    or View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                )
        }
    }

    // ---- Input handling: block escape, expose admin gesture ----

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        when (keyCode) {
            KeyEvent.KEYCODE_MENU -> {
                openAdmin()
                return true
            }
            KeyEvent.KEYCODE_BACK -> {
                registerExitPress()
                // Swallow BACK so the user can never leave the kiosk with it.
                return true
            }
        }
        return super.onKeyDown(keyCode, event)
    }

    /**
     * Quatro toques no ecrã (em qualquer ponto) em 3 s abrem a administração. Os toques continuam a
     * chegar à página; os toques enviados pelo painel "Ao vivo" vão diretos ao WebView e não contam.
     */
    override fun dispatchTouchEvent(ev: MotionEvent): Boolean {
        if (ev.actionMasked == MotionEvent.ACTION_DOWN) {
            val now = SystemClock.elapsedRealtime()
            tapTimes.addLast(now)
            while (tapTimes.isNotEmpty() && now - tapTimes.first() > 3000) tapTimes.removeFirst()
            if (tapTimes.size >= 4) {
                tapTimes.clear()
                openAdmin()
                return true
            }
        }
        return super.dispatchTouchEvent(ev)
    }

    /** Dois toques em Voltar em 2,5 s abrem a administração. */
    private fun registerExitPress(): Boolean {
        val now = SystemClock.elapsedRealtime()
        backPressTimes.addLast(now)
        while (backPressTimes.isNotEmpty() && now - backPressTimes.first() > 2500) {
            backPressTimes.removeFirst()
        }
        if (backPressTimes.size >= 2) {
            backPressTimes.clear()
            openAdmin()
            return true
        }
        return false
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        // Intentionally do nothing (kiosk).
    }

    override fun onDestroy() {
        if (RemoteAgent.frameProvider === frameProvider) RemoteAgent.frameProvider = null
        teardownWebView()
        super.onDestroy()
    }
}
