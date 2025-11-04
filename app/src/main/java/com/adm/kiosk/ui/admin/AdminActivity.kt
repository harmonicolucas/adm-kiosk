package com.adm.kiosk.ui.admin

import android.os.Bundle
import android.view.MotionEvent
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.adm.kiosk.remote.RemoteAgent
import com.adm.kiosk.remote.ScreenRemote
import com.adm.kiosk.ui.theme.AdmKioskTheme
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import kotlinx.coroutines.launch
import org.json.JSONObject

/**
 * PIN-protected administration area. Optimised for D-pad, keyboard and mouse.
 */
class AdminActivity : ComponentActivity() {

    private val vm: AdminViewModel by lazy {
        ViewModelProvider(this)[AdminViewModel::class.java]
    }

    private val remoteTouch = ScreenRemote.Touch()

    private val frameProvider: suspend (Int, Int) -> ByteArray? = { maxWidth, quality ->
        ScreenRemote.frame(this@AdminActivity, window.decorView, maxWidth, quality)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            AdmKioskTheme {
                val auth by vm.auth.collectAsState()
                if (auth.authenticated) {
                    var showSettings by remember { mutableStateOf(false) }
                    BackHandler(enabled = showSettings) { showSettings = false }
                    if (showSettings) {
                        SettingsScreen(
                            vm = vm,
                            onBack = { showSettings = false },
                        )
                    } else {
                        AdminScreen(
                            vm = vm,
                            onOpenSettings = { showSettings = true },
                            onOpenLink = { finish() },
                        )
                    }
                } else {
                    PinScreen(
                        auth = auth,
                        onSubmit = vm::submitPin,
                        onCancel = { finish() },
                    )
                }
            }
        }
        // Sessão "Ao vivo" no painel web: este ecrã também pode ser visto e controlado.
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.RESUMED) {
                RemoteAgent.inputs.collect { handleRemoteInput(it) }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        RemoteAgent.frameProvider = frameProvider
    }

    private fun handleRemoteInput(ev: JSONObject) {
        val view = window.decorView
        val x = ev.optDouble("x", 0.5).toFloat() * view.width
        val y = ev.optDouble("y", 0.5).toFloat() * view.height
        when (ev.optString("type")) {
            "click", "rightclick" -> remoteTouch.tap(view, x, y)
            "dblclick" -> { remoteTouch.tap(view, x, y); remoteTouch.tap(view, x, y) }
            "down" -> remoteTouch.send(view, MotionEvent.ACTION_DOWN, x, y)
            "move" -> remoteTouch.send(view, MotionEvent.ACTION_MOVE, x, y)
            "up" -> remoteTouch.send(view, MotionEvent.ACTION_UP, x, y)
            "key" -> when (ev.optString("key")) {
                "Back", "Escape" -> onBackPressedDispatcher.onBackPressed()
                else -> ScreenRemote.typeInto(this, ev)
            }
            "text" -> ScreenRemote.typeInto(this, ev)
        }
    }

    override fun onDestroy() {
        if (RemoteAgent.frameProvider === frameProvider) RemoteAgent.frameProvider = null
        super.onDestroy()
    }

    override fun onStop() {
        super.onStop()
        // Re-lock when leaving the admin area.
        vm.lock()
    }
}
