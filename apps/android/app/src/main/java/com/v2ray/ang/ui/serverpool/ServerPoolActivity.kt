package com.v2ray.ang.ui.serverpool

import android.app.Application
import android.net.VpnService
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.v2ray.ang.AppConfig
import com.v2ray.ang.R
import com.v2ray.ang.core.LauncherManager
import com.v2ray.ang.handler.*
import com.v2ray.ang.helper.MessageHelper
import com.v2ray.ang.ui.base.HelperBaseComponentActivity
import com.v2ray.ang.ui.compose.AppTopBar
import com.v2ray.ang.util.Utils
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import java.time.LocalTime
import java.time.format.DateTimeFormatter
import java.util.concurrent.atomic.AtomicLong
import kotlin.coroutines.resume

private val logTime = DateTimeFormatter.ofPattern("HH:mm:ss")
data class PoolLog(val id: Long, val text: String)
data class PoolScreenState(val progress: PoolProgress = PoolProgress("آماده", "برای جمع‌آوری شروع را بزنید."),
    val busy: Boolean = false, val logs: List<PoolLog> = emptyList(), val rows: List<String> = emptyList())

class ServerPoolViewModel(application: Application) : AndroidViewModel(application) {
    val state = MutableStateFlow(PoolScreenState())
    private val sequence = AtomicLong()
    private var job: Job? = null
    init { refresh() }
    private fun refresh() {
        val rows = MmkvManager.decodeServerList(ServerPoolManager.POOL_ID).mapNotNull { guid ->
            MmkvManager.decodeServerConfig(guid)?.let {
                "${it.remarks} · ${MmkvManager.decodeServerAffiliationInfo(guid)?.testDelayMillis ?: 0} ms"
            }
        }
        state.update { it.copy(rows = rows) }
    }
    fun report(progress: PoolProgress) {
        val entry = PoolLog(sequence.incrementAndGet(), "${LocalTime.now().format(logTime)} [${progress.stage}] ${progress.message}" +
            if (progress.total > 0) " · ${progress.completed}/${progress.total}" else "")
        state.update {
            val displayed = if (progress.total == 0 && progress.stage == it.progress.stage)
                progress.copy(completed = it.progress.completed, total = it.progress.total, passed = it.progress.passed, failed = it.progress.failed)
            else progress
            it.copy(progress = displayed, logs = (it.logs + entry).takeLast(300))
        }
    }
    fun clearLogs() { state.update { it.copy(logs = emptyList()) } }
    fun cancel() { report(PoolProgress("توقف", "در حال توقف و آزادسازی هسته‌های آزمون…")); job?.cancel() }
    fun start() {
        if (state.value.busy) return
        state.update { it.copy(busy = true) }
        report(PoolProgress("شروع", "اجرای جدید · 3.9.0 revision 2"))
        job = viewModelScope.launch {
            try {
                val context = getApplication<Application>()
                ServerPoolManager.run(context, { guid ->
                    withContext(Dispatchers.Main) {
                        MmkvManager.setSelectServer(guid)
                        // Wait for the daemon's ordered restart acknowledgement before inspecting its port.
                        suspendCancellableCoroutine<Unit> { continuation ->
                            MessageHelper.sendMsg2ServiceForResult(context, AppConfig.MSG_STATE_RESTART, "") { handled ->
                                if (continuation.isActive) {
                                    if (!handled) LauncherManager.startService(context, guid)
                                    continuation.resume(Unit)
                                }
                            }
                        }
                    }
                }, ::report)
                refresh()
            } catch (_: CancellationException) { report(PoolProgress("متوقف", "جمع‌آوری متوقف شد؛ استخر قبلی حفظ شد.")) }
            catch (error: Exception) { report(PoolProgress("خطا", error.message ?: "جمع‌آوری ناموفق بود.")) }
            finally { state.update { it.copy(busy = false) } }
        }
    }
}

class ServerPoolActivity : HelperBaseComponentActivity() {
    private val model: ServerPoolViewModel by viewModels()
    private val permission = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        if (it.resultCode == RESULT_OK) model.start() else model.report(PoolProgress("مجوز", "برای اتصال، مجوز VPN لازم است."))
    }
    @Composable
    override fun ScreenContent() {
        val state by model.state.collectAsState()
        var tab by remember { mutableIntStateOf(0) }
        var follow by remember { mutableStateOf(true) }
        val logScroll = rememberLazyListState()
        LaunchedEffect(state.logs.lastOrNull()?.id, follow) {
            if (follow && state.logs.isNotEmpty()) logScroll.scrollToItem(state.logs.lastIndex)
        }
        Scaffold(topBar = { AppTopBar(stringResource(R.string.title_server_pool), { finish() }) }) { padding ->
            Column(Modifier.fillMaxSize().padding(padding).padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("ساب پیش‌فرض ← اتصال ← کانال‌ها ← آزمون ← ذخیره", style = MaterialTheme.typography.labelLarge)
                ElevatedCard(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(state.progress.stage, style = MaterialTheme.typography.titleMedium)
                        Text(state.progress.message, style = MaterialTheme.typography.bodyMedium)
                        if (state.progress.total > 0) {
                            LinearProgressIndicator(progress = { (state.progress.completed.toFloat() / state.progress.total).coerceIn(0f, 1f) }, modifier = Modifier.fillMaxWidth())
                            Text("${state.progress.completed}/${state.progress.total} · پذیرفته: ${state.progress.passed} · خطا: ${state.progress.failed}")
                        } else if (state.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(enabled = !state.busy, onClick = {
                        tab = 0
                        val intent = if (SettingsManager.isVpnMode()) VpnService.prepare(this@ServerPoolActivity) else null
                        if (intent == null) model.start() else permission.launch(intent)
                    }, modifier = Modifier.weight(1f)) { Text(if (state.logs.isEmpty()) "شروع جمع‌آوری" else "اجرای دوباره") }
                    OutlinedButton(enabled = state.busy && state.progress.stage != "توقف", onClick = model::cancel) { Text("توقف") }
                }
                Text("فقط سه پاسخ معتبر تا ۹۰۰ ms پذیرفته می‌شود. نتیجهٔ هر آزمون در لاگ نمایش داده می‌شود.", style = MaterialTheme.typography.bodySmall)
                TabRow(selectedTabIndex = tab) {
                    Tab(selected = tab == 0, onClick = { tab = 0 }, text = { Text("لاگ زنده") })
                    Tab(selected = tab == 1, onClick = { tab = 1 }, text = { Text("استخر (${state.rows.size})") })
                }
                if (tab == 0) {
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        TextButton(onClick = { Utils.setClipboard(this@ServerPoolActivity, state.logs.joinToString("\n") { it.text }) }) { Text("کپی لاگ") }
                        TextButton(onClick = model::clearLogs) { Text("پاک‌کردن") }
                        TextButton(onClick = { follow = !follow }) { Text(if (follow) "توقف اسکرول" else "دنبال‌کردن") }
                    }
                    LazyColumn(Modifier.weight(1f), state = logScroll, verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        items(state.logs, key = { it.id }) { Text(it.text, style = MaterialTheme.typography.bodySmall, fontFamily = FontFamily.Monospace) }
                    }
                } else {
                    if (state.rows.isEmpty()) Text("هنوز سروری ذخیره نشده است؛ جمع‌آوری را شروع کنید.")
                    LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        items(state.rows) { Text(it, style = MaterialTheme.typography.bodyMedium) }
                    }
                }
            }
        }
    }
}
