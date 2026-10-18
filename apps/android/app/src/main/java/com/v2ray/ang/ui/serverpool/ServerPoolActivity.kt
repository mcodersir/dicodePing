package com.v2ray.ang.ui.serverpool

import android.app.Application
import android.net.VpnService
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.v2ray.ang.AppConfig
import com.v2ray.ang.handler.PoolStrings
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
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.coroutines.resume

private val logTime = DateTimeFormatter.ofPattern("HH:mm:ss")
data class PoolLog(val id: Long, val text: String)
data class PoolScreenState(val progress: PoolProgress = PoolProgress("آماده", PoolStrings.t("برای جمع‌آوری شروع را بزنید.", "Press Start to collect servers.")),
    val busy: Boolean = false, val logs: List<PoolLog> = emptyList(), val rows: List<String> = emptyList())

class ServerPoolViewModel(application: Application) : AndroidViewModel(application) {
    val state = MutableStateFlow(PoolScreenState())
    private val sequence = AtomicLong()
    private val stopRequested = AtomicBoolean(false)
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
        val visible = if (stopRequested.get() && progress.stage == "آزمون")
            progress.copy(stage = "توقف", message = PoolStrings.t("در حال پایان تست‌های فعال و آماده‌سازی ${progress.passed} نتیجهٔ موفق…", "Finishing active tests and preparing ${progress.passed} successful results…"))
        else progress
        val entry = PoolLog(sequence.incrementAndGet(), "${LocalTime.now().format(logTime)} [${PoolStrings.stage(visible.stage)}] ${visible.message}" +
            if (visible.total > 0) " · ${visible.completed}/${visible.total}" else "")
        state.update {
            val displayed = if (visible.total == 0 && visible.stage == it.progress.stage)
                visible.copy(completed = it.progress.completed, total = it.progress.total,
                    passed = maxOf(visible.passed, it.progress.passed), failed = it.progress.failed,
                    target = maxOf(visible.target, it.progress.target))
            else visible
            it.copy(progress = displayed, logs = (it.logs + entry).takeLast(300))
        }
    }
    fun clearLogs() { state.update { it.copy(logs = emptyList()) } }
    fun cancel() {
        if (state.value.progress.stage == "آزمون") {
            stopRequested.set(true)
            report(PoolProgress("توقف", PoolStrings.t("در حال توقف نرم؛ سرورهای موفق تکمیل‌شده ذخیره خواهند شد…", "Stopping; completed successful servers will be saved…"),
                passed = state.value.progress.passed, target = state.value.progress.target))
        } else {
            report(PoolProgress("توقف", PoolStrings.t("در حال توقف جمع‌آوری…", "Stopping collection…")))
            job?.cancel()
        }
    }
    fun start(options: ServerPoolOptions, ensureVpnPermission: suspend () -> Boolean) {
        if (state.value.busy) return
        val requestVersion = LauncherManager.connectionRequestVersion()
        stopRequested.set(false)
        state.update { it.copy(busy = true) }
        val normalized = options.normalized()
        report(PoolProgress("شروع", PoolStrings.t("اجرای جدید · 4.9.3 · هدف ${normalized.targetCount} سرور · ${normalized.testRounds} نوبت", "New run · 4.9.3 · target ${normalized.targetCount} servers · ${normalized.testRounds} rounds")))
        job = viewModelScope.launch {
            try {
                val context = getApplication<Application>()
                ServerPoolManager.run(context, { guid ->
                    withContext(Dispatchers.Main) {
                        if (SettingsManager.isVpnMode())
                            check(ensureVpnPermission()) { PoolStrings.t("برای اتصال fallback ساب پیش‌فرض، مجوز VPN لازم است.", "VPN permission is required for the default fallback.") }
                        if (!LauncherManager.isConnectionRequestCurrent(requestVersion)) throw kotlinx.coroutines.CancellationException("Connection cancelled")
                        MmkvManager.setSelectServer(guid)
                        // Wait for the daemon's ordered restart acknowledgement before inspecting its port.
                        val acknowledged = withTimeoutOrNull(30_000) {
                            suspendCancellableCoroutine<Unit> { continuation ->
                                MessageHelper.sendMsg2ServiceForResult(context, AppConfig.MSG_STATE_RESTART, requestVersion) { handled ->
                                    if (continuation.isActive) {
                                        if (!LauncherManager.isConnectionRequestCurrent(requestVersion)) {
                                            continuation.cancel(kotlinx.coroutines.CancellationException("Connection cancelled"))
                                        } else {
                                            if (!handled) LauncherManager.startService(context, guid, requestVersion)
                                            continuation.resume(Unit)
                                        }
                                    }
                                }
                            }
                            true
                        } ?: false
                        check(acknowledged) { PoolStrings.t("هسته به فرمان راه‌اندازی پاسخ نداد؛ لاگ اتصال را بررسی کنید.", "The core did not acknowledge startup; check connection logs.") }
                    }
                }, ::report, normalized) { stopRequested.get() }
                refresh()
            } catch (_: CancellationException) { report(PoolProgress("متوقف", PoolStrings.t("جمع‌آوری متوقف شد؛ استخر قبلی حفظ شد.", "Collection stopped; previous pool kept."))) }
            catch (error: Exception) { report(PoolProgress("خطا", error.message ?: PoolStrings.t("جمع‌آوری ناموفق بود.", "Collection failed."))) }
            finally { state.update { it.copy(busy = false) } }
        }
    }
}

class ServerPoolActivity : HelperBaseComponentActivity() {
    private val model: ServerPoolViewModel by viewModels()
    private var pendingOptions = ServerPoolOptions()
    private var permissionResult: CompletableDeferred<Boolean>? = null
    private val permission = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        permissionResult?.complete(it.resultCode == RESULT_OK)
        permissionResult = null
    }

    private suspend fun ensureVpnPermission(): Boolean = withContext(Dispatchers.Main.immediate) {
        val intent = VpnService.prepare(this@ServerPoolActivity) ?: return@withContext true
        val deferred = CompletableDeferred<Boolean>()
        permissionResult = deferred
        permission.launch(intent)
        try { deferred.await() }
        finally { if (permissionResult === deferred) permissionResult = null }
    }

    override fun onDestroy() {
        permissionResult?.cancel()
        permissionResult = null
        super.onDestroy()
    }
    @Composable
    override fun ScreenContent() {
        val state by model.state.collectAsState()
        var tab by remember { mutableIntStateOf(0) }
        var follow by remember { mutableStateOf(true) }
        var targetText by rememberSaveable { mutableStateOf("20") }
        var roundsText by rememberSaveable { mutableStateOf("3") }
        val logScroll = rememberLazyListState()
        LaunchedEffect(state.logs.lastOrNull()?.id, follow) {
            if (follow && state.logs.isNotEmpty()) logScroll.scrollToItem(state.logs.lastIndex)
        }
        Scaffold(topBar = { AppTopBar(stringResource(R.string.title_server_pool), { finish() }) }) { padding ->
            Column(Modifier.fillMaxSize().padding(padding).padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(stringResource(R.string.pool_ui_0), style = MaterialTheme.typography.labelLarge)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(value = targetText,
                        onValueChange = { value -> targetText = value.filter(Char::isDigit).take(3) },
                        enabled = !state.busy, singleLine = true, label = { Text(stringResource(R.string.pool_ui_1)) },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), modifier = Modifier.weight(1f))
                    OutlinedTextField(value = roundsText,
                        onValueChange = { value -> roundsText = value.filter(Char::isDigit).take(2) },
                        enabled = !state.busy, singleLine = true, label = { Text(stringResource(R.string.pool_ui_2)) },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), modifier = Modifier.weight(1f))
                }
                ElevatedCard(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(PoolStrings.stage(state.progress.stage), style = MaterialTheme.typography.titleMedium)
                        Text(state.progress.message, style = MaterialTheme.typography.bodyMedium)
                        if (state.progress.total > 0) {
                            LinearProgressIndicator(progress = { (state.progress.completed.toFloat() / state.progress.total).coerceIn(0f, 1f) }, modifier = Modifier.fillMaxWidth())
                            Text(if (state.progress.stage == "جمع‌آوری")
                                "${state.progress.completed}/${state.progress.total} · ${PoolStrings.t("کاندید", "Candidates")}: ${state.progress.passed} · ${PoolStrings.t("خطا", "Errors")}: ${state.progress.failed}"
                            else "${state.progress.completed}/${state.progress.total} · ${PoolStrings.t("موفق", "Passed")}: ${state.progress.passed}${if (state.progress.target > 0) "/${state.progress.target}" else ""} · ${PoolStrings.t("ناموفق", "Failed")}: ${state.progress.failed}")
                        } else if (state.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(enabled = !state.busy, onClick = {
                        tab = 0
                        pendingOptions = ServerPoolOptions(
                            (targetText.toIntOrNull() ?: 20).coerceIn(ServerPoolOptions.MIN_TARGET_COUNT, ServerPoolOptions.MAX_TARGET_COUNT),
                            (roundsText.toIntOrNull() ?: 3).coerceIn(ServerPoolOptions.MIN_TEST_ROUNDS, ServerPoolOptions.MAX_TEST_ROUNDS))
                        targetText = pendingOptions.targetCount.toString()
                        roundsText = pendingOptions.testRounds.toString()
                        model.start(pendingOptions, ::ensureVpnPermission)
                    }, modifier = Modifier.weight(1f)) { Text(if (state.logs.isEmpty()) stringResource(R.string.pool_ui_3) else stringResource(R.string.pool_ui_4)) }
                    OutlinedButton(enabled = state.busy && state.progress.stage !in setOf("توقف", "ذخیره", "پایان", "متوقف"),
                        onClick = model::cancel) { Text(stringResource(R.string.pool_ui_5)) }
                }
                Text(stringResource(R.string.pool_ui_6), style = MaterialTheme.typography.bodySmall)
                TabRow(selectedTabIndex = tab) {
                    Tab(selected = tab == 0, onClick = { tab = 0 }, text = { Text(stringResource(R.string.pool_ui_7)) })
                    Tab(selected = tab == 1, onClick = { tab = 1 }, text = { Text("${stringResource(R.string.title_server_pool)} (${state.rows.size})") })
                }
                if (tab == 0) {
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        TextButton(onClick = { Utils.setClipboard(this@ServerPoolActivity, state.logs.joinToString("\n") { it.text }) }) { Text(stringResource(R.string.pool_ui_8)) }
                        TextButton(onClick = model::clearLogs) { Text(stringResource(R.string.pool_ui_9)) }
                        TextButton(onClick = { follow = !follow }) { Text(if (follow) stringResource(R.string.pool_ui_10) else stringResource(R.string.pool_ui_11)) }
                    }
                    LazyColumn(Modifier.weight(1f), state = logScroll, verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        items(state.logs, key = { it.id }) { Text(it.text, style = MaterialTheme.typography.bodySmall, fontFamily = FontFamily.Monospace) }
                    }
                } else {
                    if (state.rows.isEmpty()) Text(stringResource(R.string.pool_ui_12))
                    LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        items(state.rows) { Text(it, style = MaterialTheme.typography.bodyMedium) }
                    }
                }
            }
        }
    }
}
