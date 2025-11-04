package com.adm.kiosk.web

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Color
import android.os.Build
import android.view.ViewGroup
import android.webkit.RenderProcessGoneDetail
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient

/**
 * Callbacks surfaced to the hosting activity.
 */
interface KioskWebListener {
    fun onPageStarted(url: String?)

    /** Called only when the main page loaded successfully (never after a failed load). */
    fun onPageFinished(url: String?)
    fun onError(isMainFrame: Boolean, description: String?)

    /** The WebView renderer died; the host must discard and rebuild the WebView. */
    fun onRendererGone() {}
}

/** Result of one auto-rotation step on the page. */
enum class ScrollResult { FIT, SCROLLED, TOP }

object WebViewFactory {

    /**
     * Builds a fully configured, full-screen WebView tuned for digital-signage kiosk usage.
     * [zoomPercent] is read on every page load so the latest admin value is always applied.
     */
    @SuppressLint("SetJavaScriptEnabled")
    fun create(
        context: Context,
        zoomPercent: () -> Int,
        listener: KioskWebListener,
    ): WebView {
        val webView = WebView(context)
        webView.layoutParams = ViewGroup.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.MATCH_PARENT,
        )
        webView.setBackgroundColor(Color.BLACK)
        webView.isVerticalScrollBarEnabled = false
        webView.isHorizontalScrollBarEnabled = false
        webView.overScrollMode = WebView.OVER_SCROLL_NEVER

        with(webView.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            javaScriptCanOpenWindowsAutomatically = false
            setSupportMultipleWindows(false)

            // Viewport / scaling — make content fill and fit the screen.
            useWideViewPort = true
            loadWithOverviewMode = true
            builtInZoomControls = false
            displayZoomControls = false
            setSupportZoom(false)

            // Zoom is applied as a visual scale (see applyZoom) so the text never reflows.
            textZoom = 100

            cacheMode = WebSettings.LOAD_DEFAULT
            allowFileAccess = false
            allowContentAccess = false
            mediaPlaybackRequiresUserGesture = false
            mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
            loadsImagesAutomatically = true
        }

        webView.setLayerType(WebView.LAYER_TYPE_HARDWARE, null)

        webView.webViewClient = object : WebViewClient() {
            // WebView calls onPageFinished even after a failed load; this flag keeps the
            // failure visible so the host keeps retrying instead of showing a black page.
            private var mainFrameFailed = false

            override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                mainFrameFailed = false
                listener.onPageStarted(url)
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                if (mainFrameFailed) return
                applyPageTweaks(view, zoomPercent())
                listener.onPageFinished(url)
            }

            override fun shouldOverrideUrlLoading(
                view: WebView?,
                request: WebResourceRequest?,
            ): Boolean = false

            override fun onReceivedError(
                view: WebView?,
                request: WebResourceRequest?,
                error: WebResourceError?,
            ) {
                if (request?.isForMainFrame != false) {
                    mainFrameFailed = true
                    listener.onError(true, error?.description?.toString())
                }
            }

            @Deprecated("Deprecated in Java")
            override fun onReceivedError(
                view: WebView?,
                errorCode: Int,
                description: String?,
                failingUrl: String?,
            ) {
                if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) {
                    mainFrameFailed = true
                    listener.onError(true, description)
                }
            }

            override fun onReceivedHttpError(
                view: WebView?,
                request: WebResourceRequest?,
                errorResponse: WebResourceResponse?,
            ) {
                // A FIDS server still booting after a power cut typically answers 502/503.
                val status = errorResponse?.statusCode ?: return
                if (request?.isForMainFrame == true && status >= 400) {
                    mainFrameFailed = true
                    listener.onError(true, "HTTP $status")
                }
            }

            override fun onRenderProcessGone(view: WebView?, detail: RenderProcessGoneDetail?): Boolean {
                listener.onRendererGone()
                return true
            }
        }

        webView.webChromeClient = WebChromeClient()
        return webView
    }

    /**
     * Visual zoom: scales the whole page like a picture (CSS transform), so lines, columns
     * and line breaks of the text stay exactly as the page designed them.
     */
    fun applyZoom(webView: WebView, zoomPercent: Int) {
        webView.evaluateJavascript(zoomJs(zoomPercent), null)
    }

    private fun zoomJs(zoomPercent: Int): String {
        val scale = zoomPercent.coerceIn(25, 400) / 100.0
        return """
            (function() {
              var b = document.body; if (!b) return;
              if ($scale === 1) { b.style.transform = ''; b.style.transformOrigin = ''; }
              else { b.style.transformOrigin = 'top center'; b.style.transform = 'scale($scale)'; }
            })();
        """.trimIndent()
    }

    /**
     * After page load: adds a viewport meta tag if missing, hides scrollbars and applies the
     * visual zoom.
     */
    private fun applyPageTweaks(view: WebView?, zoomPercent: Int) {
        view ?: return
        val js = """
            (function() {
              try {
                var vp = document.querySelector('meta[name="viewport"]');
                if (!vp) {
                  vp = document.createElement('meta');
                  vp.name = 'viewport';
                  vp.content = 'width=device-width, initial-scale=1.0';
                  var head = document.getElementsByTagName('head')[0];
                  if (head) head.appendChild(vp);
                }
                if (!document.getElementById('_adm_kiosk_style')) {
                  var st = document.createElement('style');
                  st.id = '_adm_kiosk_style';
                  st.textContent = '::-webkit-scrollbar{width:0!important;height:0!important;display:none}';
                  (document.head || document.documentElement).appendChild(st);
                }
              } catch (e) {}
            })();
        """.trimIndent()
        view.evaluateJavascript(js, null)
        view.evaluateJavascript(zoomJs(zoomPercent), null)
    }

    /**
     * Auto-rotation of cut-off content (e.g. a long flight list). Finds the element that
     * holds hidden rows (the page itself or an inner scrolling panel) and advances one
     * screen; after the last screen it returns to the top. Does nothing when everything
     * already fits ([ScrollResult.FIT]).
     */
    fun autoScrollStep(webView: WebView, onResult: (ScrollResult) -> Unit) {
        val js = """
            (function() {
              try {
                var root = document.scrollingElement || document.documentElement;
                var cands = [root];
                var els = document.querySelectorAll('body,div,section,main,article,table,tbody,ul,ol');
                for (var i = 0; i < els.length && i < 4000; i++) {
                  var e = els[i];
                  if (e === root || e.clientHeight < 120) continue;
                  var oy = getComputedStyle(e).overflowY;
                  if (oy === 'visible') continue;
                  cands.push(e);
                }
                var best = null, bestArea = 0;
                for (var j = 0; j < cands.length; j++) {
                  var c = cands[j];
                  if (c.scrollHeight - c.clientHeight > 20) {
                    var area = c.clientHeight * c.clientWidth;
                    if (area > bestArea) { best = c; bestArea = area; }
                  }
                }
                if (!best) return 'FIT';
                // Only content that matters counts (text, images, video, charts); empty
                // or solid-colour blocks below the visible area never trigger scrolling.
                var isRoot = best === root;
                var host = isRoot ? (document.body || root) : best;
                var top0 = isRoot ? -window.scrollY : best.getBoundingClientRect().top - best.scrollTop;
                var bottom = 0;
                function visible(el) {
                  for (var p = el, k = 0; p && p !== host && k < 6; p = p.parentElement, k++) {
                    var cs = getComputedStyle(p);
                    if (cs.visibility === 'hidden' || cs.opacity === '0') return false;
                  }
                  return true;
                }
                function consider(el) {
                  var r = el.getBoundingClientRect();
                  if (r.width < 4 || r.height < 4) return;
                  var b = r.bottom - top0;
                  if (b > bottom && visible(el)) bottom = b;
                }
                var walker = document.createTreeWalker(host, NodeFilter.SHOW_TEXT, null);
                var seen = 0, n;
                while ((n = walker.nextNode()) && seen < 20000) {
                  seen++;
                  if (!/\S/.test(n.nodeValue) || !n.parentElement) continue;
                  var tag = n.parentElement.tagName;
                  if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'NOSCRIPT') continue;
                  consider(n.parentElement);
                }
                var media = host.querySelectorAll('img,svg,canvas,video,iframe,object,embed,input,select,textarea');
                for (var m = 0; m < media.length && m < 3000; m++) consider(media[m]);
                var max = Math.min(best.scrollHeight - best.clientHeight, Math.ceil(bottom - best.clientHeight + 10));
                if (max <= 20) {
                  if (best.scrollTop <= 5) return 'FIT';
                  max = 0;
                }
                var page = Math.max(60, Math.floor(best.clientHeight * 0.9));
                var next;
                if (best.scrollTop >= max - 5) next = 0;
                else next = Math.min(max, best.scrollTop + page);
                try { best.scrollTo({ top: next, behavior: 'smooth' }); }
                catch (e2) { best.scrollTop = next; }
                return next === 0 ? 'TOP' : 'SCROLLED';
              } catch (e) { return 'FIT'; }
            })();
        """.trimIndent()
        webView.evaluateJavascript(js) { raw ->
            val result = when (raw?.trim('"')) {
                "SCROLLED" -> ScrollResult.SCROLLED
                "TOP" -> ScrollResult.TOP
                else -> ScrollResult.FIT
            }
            onResult(result)
        }
    }
}
