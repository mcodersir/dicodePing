package com.v2ray.ang.ui.serverpool

import android.app.Application
import android.net.VpnService
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.v2ray.ang.R
import com.v2ray.ang.core.LauncherManager
import com.v2ray.ang.handler.MmkvManager
import com.v2ray.ang.handler.ServerPoolManager
import com.v2ray.ang.handler.SettingsManager
import com.v2ray.ang.dto.UrlContentRequest
import com.v2ray.ang.ui.base.HelperBaseComponentActivity
import com.v2ray.ang.ui.compose.AppTopBar
import com.v2ray.ang.util.HttpUtil
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow

class ServerPoolViewModel(application: Application) : AndroidViewModel(application) {
    val status = MutableStateFlow("آمادهٔ جمع‌آوری")
    val busy = MutableStateFlow(false)
    val rows = MutableStateFlow<List<String>>(emptyList())
    private var job: Job? = null
    init { refresh() }
    private fun refresh() {
        rows.value = MmkvManager.decodeServerList(ServerPoolManager.POOL_ID).mapNotNull { guid ->
            MmkvManager.decodeServerConfig(guid)?.let {
                "${it.remarks} · ${MmkvManager.decodeServerAffiliationInfo(guid)?.testDelayMillis ?: 0} ms"
            }
        }
    }
    fun cancel() { status.value = "در حال توقف…"; job?.cancel() }
    fun start() {
        if (busy.value) return
        busy.value = true
        job = viewModelScope.launch {
            try {
                val context = getApplication<Application>()
                ServerPoolManager.run(context, { guid ->
                    withContext(Dispatchers.Main) {
                        MmkvManager.setSelectServer(guid)
                        LauncherManager.restartServiceOrStart(context) { LauncherManager.startService(context, guid) }
                    }
                    // Require a working authenticated local proxy before downloading channels.
                    delay(1500)
                    var ready = false
                    repeat(12) {
                        ensureActive()
                        if (!ready) {
                            ready = !HttpUtil.getUrlContent(UrlContentRequest(
                                url = ServerPoolManager.CHANNELS_URL, timeout = 2000,
                                httpPort = SettingsManager.getHttpPort(),
                                proxyUsername = SettingsManager.getSocksUsername(), proxyPassword = SettingsManager.getSocksPassword()
                            )).isNullOrBlank()
                            if (!ready) delay(500)
                        }
                    }
                    check(ready) { "اتصال ساب پیش‌فرض برقرار نشد؛ دوباره تلاش کنید." }
                }, { status.value = it })
                refresh()
            } catch (_: CancellationException) { status.value = "متوقف شد؛ استخر قبلی حفظ شد." }
            catch (error: Exception) { status.value = error.message ?: "جمع‌آوری ناموفق بود." }
            finally { busy.value = false }
        }
    }
}

class ServerPoolActivity : HelperBaseComponentActivity() {
    private val model: ServerPoolViewModel by viewModels()
    private val permission = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        if (it.resultCode == RESULT_OK) model.start() else model.status.value = "برای اتصال، مجوز VPN لازم است."
    }
    @Composable
    override fun ScreenContent() {
        val status by model.status.collectAsState()
        val busy by model.busy.collectAsState()
        val rows by model.rows.collectAsState()
        Scaffold(topBar = { AppTopBar(stringResource(R.string.title_server_pool), { finish() }) }) { padding ->
            Column(Modifier.fillMaxSize().padding(padding).padding(16.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                Text("اتصال خودکار از ساب پیش‌فرض؛ حداکثر ۴ کانفیگ از پیام‌های ۷ روز اخیر هر کانال. فقط سه پاسخ معتبر تا ۹۰۰ میلی‌ثانیه پذیرفته می‌شود.")
                Button(enabled = !busy, onClick = {
                    val intent = VpnService.prepare(this@ServerPoolActivity)
                    if (intent == null) model.start() else permission.launch(intent)
                }, modifier = Modifier.fillMaxWidth()) { Text("جمع‌آوری و بروزرسانی استخر") }
                if (busy) {
                    LinearProgressIndicator(Modifier.fillMaxWidth())
                    TextButton(onClick = model::cancel) { Text("توقف") }
                }
                Text(status, style = MaterialTheme.typography.bodyMedium)
                LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(rows) { Text(it, style = MaterialTheme.typography.bodyMedium) }
                }
            }
        }
    }
}
