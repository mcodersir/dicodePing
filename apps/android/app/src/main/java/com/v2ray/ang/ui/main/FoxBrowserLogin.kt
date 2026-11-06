package com.v2ray.ang.ui.main

import android.annotation.SuppressLint
import android.net.Uri
import android.webkit.WebView
import android.webkit.WebViewClient
import android.webkit.WebResourceRequest
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature
import androidx.webkit.ProxyConfig
import androidx.webkit.ProxyController
import com.v2ray.ang.core.FoxProcess
import com.v2ray.ang.core.FoxAccounts
import com.v2ray.ang.core.FoxError
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.util.UUID

internal fun foxTrustedOrigin(uri: Uri?): Boolean = uri?.scheme == "https" && uri.host == "accounts.firefox.com" && (uri.port == -1 || uri.port == 443) && uri.userInfo == null

@SuppressLint("SetJavaScriptEnabled")
@Composable
internal fun FoxBrowserLogin(onDismiss: () -> Unit, onComplete: (String) -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val fa = context.resources.configuration.locales[0].language == "fa"
    val nonce = remember { UUID.randomUUID().toString() }
    var busy by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf("") }
    var web by remember { mutableStateOf<WebView?>(null) }
    var disposed by remember { mutableStateOf(false) }
    var pendingSession by remember { mutableStateOf("") }
    var pendingEmail by remember { mutableStateOf("") }
    val signInProxy = remember { FoxProcess(context) }
    val script = remember { context.assets.open("fox-browser.js").bufferedReader().use { it.readText() }.replace("__DICODE_NONCE__", JSONObject.quote(nonce)) }
    DisposableEffect(Unit) { onDispose {
        disposed = true; pendingSession = ""; pendingEmail = ""
        signInProxy.close()
        if (WebViewFeature.isFeatureSupported(WebViewFeature.PROXY_OVERRIDE)) ProxyController.getInstance().clearProxyOverride({ it.run() }, {})
    } }
    fun receive(view: WebView, payload: String) {
        if (disposed || payload.length > 8192 || !foxTrustedOrigin(Uri.parse(view.url ?: ""))) return
        val data = runCatching { JSONObject(payload) }.getOrNull() ?: return
        if (data.optString("nonce") != nonce) return
        if (data.optString("kind") == "pending_session") {
            val session=data.optString("session_token");val accountEmail=data.optString("email")
            if (Regex("^[a-fA-F0-9]{64}$").matches(session) && accountEmail.length<=254 && accountEmail.contains('@')) { pendingSession=session;pendingEmail=accountEmail }
            return
        }
        if (data.optString("kind") == "bridge_ready") {
            if (pendingSession.isNotEmpty()) view.evaluateJavascript("window.__dicodeFoxRestore && window.__dicodeFoxRestore(" + JSONObject.quote(pendingSession) + "," + JSONObject.quote(pendingEmail) + ")", null)
            return
        }
        if (data.optString("kind") == "auth_progress") {
            status = if (fa) "در حال دریافت مجوز حساب از موزیلا…" else "Requesting the account grant from Mozilla…"
            return
        }
        if (data.optString("kind") == "auth_error") {
            status = when (data.optString("code")) {
                "session_unconfirmed" -> if (fa) "کد ایمیل یا تأیید دومرحله‌ای را در همین صفحه کامل کنید." else "Complete email or two-factor verification on this page."
                "verification_required" -> if (fa) "موزیلا درخواست توکن این مرورگر را رد کرد. نشست ذخیره نشد؛ پس از رفع بررسی امنیتی، تلاش دوباره را بزنید." else "Mozilla refused this browser's token request. No session was saved. Complete its security check, then retry."
                "login_required" -> if (fa) "موزیلا این نشست را نپذیرفت؛ دوباره وارد حساب شوید." else "Mozilla rejected this session. Sign in again."
                else -> if (fa) "تبادل توکن مرورگر کامل نشد؛ اتصال را بررسی کنید و تلاش دوباره را بزنید." else "Browser token exchange did not complete. Check the connection and retry."
            }
            return
        }
        if (busy) return
        val grant = data.optString("kind") == "grant"
        if (!grant && data.optString("kind") != "session") return
        if (grant && com.v2ray.ang.core.FoxBrowserGrant.state(data) == null) return
        val token = data.optString("session_token"); val email = data.optString("email")
        if (!grant && (!Regex("^[a-fA-F0-9]{64}$").matches(token) || email.length > 254 || !email.contains('@'))) return
        busy = true; status = if (fa) "در حال تأیید نشست امن…" else "Verifying account session…"
        scope.launch {
            try {
                val account = withContext(Dispatchers.IO) { if (grant) FoxAccounts.browserGrant(context, data) else FoxAccounts.browserLogin(context, email, token) }
                if (!disposed) onComplete(account.id)
            } catch (e: Exception) {
                if (!disposed) {
                    status = if (e is FoxError && e.code == "session_unconfirmed") {
                        if (fa) "کد تأیید یا تأیید دومرحله‌ای را در همین صفحه کامل کنید." else "Complete email or two-factor verification on this page."
                    } else if (fa) "تأیید نشست کامل نشد؛ دوباره تلاش کنید یا ZIP گزارش خطا را ارسال کنید." else "Session confirmation failed. Retry or share the diagnostic ZIP."
                    view.evaluateJavascript("window.__dicodeFoxWaiting && window.__dicodeFoxWaiting()", null)
                }
            } finally { busy = false }
        }
    }
    Dialog(onDismissRequest = onDismiss, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(Modifier.fillMaxSize()) {
            Column(Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing).imePadding()) {
                Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("accounts.firefox.com", modifier = Modifier.padding(vertical = 16.dp))
                    TextButton(onClick = onDismiss) { Text(if (fa) "بازگشت" else "Back") }
                }
                if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
                if (status.isNotBlank()) {
                    Text(status, modifier = Modifier.padding(12.dp))
                    TextButton(onClick = { web?.evaluateJavascript("window.__dicodeFoxRetry && window.__dicodeFoxRetry()", null) }, enabled = !busy) { Text(if (fa) "تلاش دوباره" else "Retry") }
                }
                AndroidView(modifier = Modifier.weight(1f).fillMaxWidth(), factory = { ctx ->
                    try { WebView(ctx).apply {
                        web = this
                        settings.javaScriptEnabled = true; settings.domStorageEnabled = true
                        settings.allowFileAccess = false; settings.allowContentAccess = false
                        settings.mixedContentMode = android.webkit.WebSettings.MIXED_CONTENT_NEVER_ALLOW
                        settings.saveFormData = false
                        importantForAutofill = android.view.View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS
                        settings.userAgentString = "Mozilla/5.0 (Android 14; Mobile; rv:158.0) Gecko/158.0 Firefox/158.0"
                        android.webkit.CookieManager.getInstance().setAcceptCookie(true)
                        if (!WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) {
                            status = if (fa) "Android System WebView را به‌روز کنید و دوباره وارد شوید." else "Update Android System WebView and sign in again."
                        } else {
                            WebViewCompat.addWebMessageListener(this, "dicodeFox", setOf("https://accounts.firefox.com")) { view, message, origin, mainFrame, _ ->
                                if (mainFrame && foxTrustedOrigin(origin)) runCatching { message.data }.getOrNull()?.let { payload -> view.post { receive(view, payload) } }
                            }
                            val documentStart = WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT)
                            if (documentStart) WebViewCompat.addDocumentStartJavaScript(this, script, setOf("https://accounts.firefox.com"))
                            webViewClient = object : WebViewClient() {
                                override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean = request.isForMainFrame && !foxTrustedOrigin(request.url)
                                override fun onPageStarted(view: WebView, url: String?, icon: android.graphics.Bitmap?) {
                                    if (!documentStart && foxTrustedOrigin(Uri.parse(url ?: ""))) view.evaluateJavascript(script, null)
                                }
                                override fun onPageFinished(view: WebView, url: String?) {
                                    if (!documentStart && foxTrustedOrigin(Uri.parse(url ?: ""))) {
                                        view.evaluateJavascript(script, null)
                                        if (pendingSession.isNotEmpty()) view.evaluateJavascript("window.__dicodeFoxRestore && window.__dicodeFoxRestore(" + JSONObject.quote(pendingSession) + "," + JSONObject.quote(pendingEmail) + ")", null)
                                    }
                                }
                            }
                            // Cookies and browser storage are never added to logs or diagnostic ZIPs.
                            val loginUrl = "https://accounts.firefox.com/?context=fx_desktop_v3&service=sync&action=email"
                            val browser = this
                            scope.launch {
                                try {
                                    val address = withContext(Dispatchers.IO) { signInProxy.startSignInProxy() }
                                    if (!disposed && WebViewFeature.isFeatureSupported(WebViewFeature.PROXY_OVERRIDE)) {
                                        ProxyController.getInstance().setProxyOverride(ProxyConfig.Builder().addProxyRule("http://$address").build(), { it.run() }) {
                                            browser.post { if (!disposed) browser.loadUrl(loginUrl) }
                                        }
                                    } else if (!disposed) browser.loadUrl(loginUrl)
                                } catch (e: Exception) {
                                    if (!disposed) { status = if (fa) "مسیر امن ورود آماده نشد؛ دوباره تلاش کنید." else "The sign-in route could not start. Retry." }
                                }
                            }
                        }
                    } } catch (e: Exception) {
                        android.widget.TextView(ctx).apply { text = if (fa) "مرورگر سیستم اندروید آماده نیست؛ Android System WebView را به‌روز کنید." else "Android System WebView is unavailable. Update it and retry." }
                    }
                }, onRelease = { view ->
                    disposed = true; web = null
                    if (view is WebView) {
                    view.stopLoading(); if (WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) WebViewCompat.removeWebMessageListener(view, "dicodeFox")
                    view.loadUrl("about:blank"); view.clearHistory(); view.destroy()
                    }
                })
            }
        }
    }
}
