package com.adm.kiosk.remote

import android.graphics.Bitmap
import android.graphics.Canvas
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.InputDevice
import android.view.KeyCharacterMap
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.PixelCopy
import android.view.View
import androidx.activity.ComponentActivity
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import kotlin.coroutines.resume

/** Captura do ecrã e controlo remoto partilhados pelos ecrãs da aplicação (apresentação e administração). */
object ScreenRemote {

    val KEYS = mapOf(
        "Enter" to KeyEvent.KEYCODE_ENTER,
        "Backspace" to KeyEvent.KEYCODE_DEL,
        "Delete" to KeyEvent.KEYCODE_FORWARD_DEL,
        "Tab" to KeyEvent.KEYCODE_TAB,
        "ArrowUp" to KeyEvent.KEYCODE_DPAD_UP,
        "ArrowDown" to KeyEvent.KEYCODE_DPAD_DOWN,
        "ArrowLeft" to KeyEvent.KEYCODE_DPAD_LEFT,
        "ArrowRight" to KeyEvent.KEYCODE_DPAD_RIGHT,
        "PageUp" to KeyEvent.KEYCODE_PAGE_UP,
        "PageDown" to KeyEvent.KEYCODE_PAGE_DOWN,
        "Home" to KeyEvent.KEYCODE_MOVE_HOME,
        "End" to KeyEvent.KEYCODE_MOVE_END,
        "Space" to KeyEvent.KEYCODE_SPACE,
        " " to KeyEvent.KEYCODE_SPACE,
    )

    /** Imagem JPEG da janela da atividade (ou null). */
    suspend fun frame(activity: ComponentActivity, view: View, maxWidth: Int, quality: Int): ByteArray? =
        withContext(Dispatchers.Main) {
            suspendCancellableCoroutine { cont ->
                capture(activity, view, maxWidth, quality) { if (cont.isActive) cont.resume(it) }
            }
        }

    fun capture(activity: ComponentActivity, view: View, maxWidth: Int, quality: Int, onDone: (ByteArray?) -> Unit) {
        if (view.width <= 0 || view.height <= 0) return onDone(null)
        // PixelCopy scales into the destination, so 4K screens never allocate full-size bitmaps.
        val scale = minOf(1f, maxWidth.toFloat() / view.width)
        val w = (view.width * scale).toInt().coerceAtLeast(1)
        val h = (view.height * scale).toInt().coerceAtLeast(1)
        val bmp = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        val encode = {
            activity.lifecycleScope.launch {
                val bytes = withContext(Dispatchers.Default) { encodeJpeg(bmp, quality) }
                bmp.recycle()
                onDone(bytes)
            }
        }
        val drawFallback = {
            runCatching {
                val canvas = Canvas(bmp)
                canvas.scale(scale, scale)
                view.draw(canvas)
            }
            encode()
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && activity.hasWindowFocus()) {
            try {
                PixelCopy.request(activity.window, bmp, { result ->
                    if (result == PixelCopy.SUCCESS) encode() else drawFallback()
                }, Handler(Looper.getMainLooper()))
            } catch (_: Exception) {
                drawFallback()
            }
        } else {
            drawFallback()
        }
    }

    private fun encodeJpeg(src: Bitmap, quality: Int): ByteArray? = runCatching {
        ByteArrayOutputStream().use { out ->
            src.compress(Bitmap.CompressFormat.JPEG, quality, out)
            out.toByteArray()
        }
    }.getOrNull()

    /** Toque remoto (premir/mover/largar) entregue diretamente a uma vista. */
    class Touch {
        private var downAt = 0L

        fun send(view: View, action: Int, x: Float, y: Float) {
            val now = SystemClock.uptimeMillis()
            if (action == MotionEvent.ACTION_DOWN) downAt = now
            if (downAt == 0L) return
            val ev = MotionEvent.obtain(downAt, now, action, x, y, 0)
            ev.source = InputDevice.SOURCE_TOUCHSCREEN
            view.dispatchTouchEvent(ev)
            ev.recycle()
            if (action == MotionEvent.ACTION_UP) downAt = 0L
        }

        fun tap(view: View, x: Float, y: Float) {
            send(view, MotionEvent.ACTION_DOWN, x, y)
            send(view, MotionEvent.ACTION_UP, x, y)
        }
    }

    /** Teclas e texto do administrador para um ecrã nativo (sem página web). */
    fun typeInto(activity: ComponentActivity, ev: JSONObject) {
        val text = when (ev.optString("type")) {
            "text" -> ev.optString("text")
            "key" -> ev.optString("key")
            else -> return
        }
        val code = if (ev.optString("type") == "key") KEYS[text] else null
        if (code != null) {
            activity.dispatchKeyEvent(KeyEvent(KeyEvent.ACTION_DOWN, code))
            activity.dispatchKeyEvent(KeyEvent(KeyEvent.ACTION_UP, code))
            return
        }
        if (ev.optString("type") == "key" && text.length != 1) return
        KeyCharacterMap.load(KeyCharacterMap.VIRTUAL_KEYBOARD).getEvents(text.toCharArray())
            ?.forEach { activity.dispatchKeyEvent(it) }
    }
}
