package com.v2ray.ang.ui.main

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.v2ray.ang.R
import com.v2ray.ang.core.FoxAccount
import com.v2ray.ang.core.FoxAccounts
import com.v2ray.ang.core.FoxError
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.launch
import java.text.DateFormat
import java.util.Date

@Composable
internal fun FoxScreen(onDismiss: () -> Unit, onChanged: () -> Unit, onConnect: (String) -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var accounts by remember { mutableStateOf<List<FoxAccount>>(emptyList()) }
    var selected by remember { mutableStateOf<String?>(null) }
    var country by remember { mutableStateOf("REC") }
    var countries by remember { mutableStateOf(listOf("REC")) }
    var expandedAccounts by remember { mutableStateOf(false) }
    var expandedCountries by remember { mutableStateOf(false) }
    var email by remember { mutableStateOf("") }; var password by remember { mutableStateOf("") }; var code by remember { mutableStateOf("") }
    var adding by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf("") }; var busy by remember { mutableStateOf(false) }
    val current = accounts.firstOrNull { it.id == selected }
    val signIn = adding || current == null
    val pending = !adding && current?.pending == true
    val ready = !adding && current != null && !current.pending
    val waiting = stringResource(R.string.fox_waiting)
    val verified = stringResource(R.string.fox_synced)
    val needsCode = stringResource(R.string.fox_needs_code)
    val fa = context.resources.configuration.locales[0].language == "fa"
    fun error(e: Exception) = if (fa && e is FoxError) when(e.code) {
        "credentials" -> "ایمیل یا رمز عبور درست نیست."
        "login_required" -> "نشست موزیلا منقضی یا رد شده است؛ دوباره وارد شوید."
        "activation_required" -> "فعال‌سازی Firefox VPN رد شد؛ دوباره تلاش کنید یا وارد حساب شوید."
        "network" -> "ارتباط با سرویس برقرار نشد؛ اتصال اینترنت را بررسی کنید."
        "input" -> "اطلاعات واردشده معتبر نیست؛ ایمیل و کد تأیید را بررسی کنید."
        "quota_exceeded" -> "سهمیه یا سقف درخواست حساب تمام شده؛ زمان بازنشانی را بررسی کنید."
        "verification_required" -> "تأیید تعاملی حساب را در سایت Mozilla کامل کنید و دوباره تلاش کنید."
        "unreachable" -> "هیچ مسیر روباه از آزمون واقعی عبور نکرد؛ اتصال مستقیم جایگزین نمی‌شود."
        else -> "عملیات روباه ناموفق بود؛ اطلاعات ورودی و اتصال را بررسی کنید."
    } else e.message.orEmpty()
    fun run(work: suspend () -> String?) {
        if (busy) return
        busy = true; status = waiting
        scope.launch {
            try {
                val id = withContext(Dispatchers.IO) { work() }
                accounts = withContext(Dispatchers.IO) { FoxAccounts.list(context) }
                selected = id ?: accounts.firstOrNull()?.id
                adding = false
                country = accounts.firstOrNull { it.id == selected }?.country ?: "REC"
                onChanged()
                status = if (accounts.firstOrNull { it.id == selected }?.pending == true) needsCode else verified
            } catch (e: Exception) {
                status = error(e)
                accounts = withContext(Dispatchers.IO) { FoxAccounts.list(context) }
                selected = accounts.firstOrNull { it.email.equals(email.trim(), true) }?.id ?: selected ?: accounts.firstOrNull()?.id
                if (selected != null) adding = false
            }
            finally { password = ""; busy = false }
        }
    }
    LaunchedEffect(Unit) {
        try {
            accounts = withContext(Dispatchers.IO) { FoxAccounts.list(context) }; selected = accounts.firstOrNull()?.id; country = accounts.firstOrNull()?.country ?: "REC"
            val locations = withContext(Dispatchers.IO) { FoxAccounts.request(context, org.json.JSONObject().put("operation", "locations")).getJSONArray("locations") }
            countries = listOf("REC") + (0 until locations.length()).map { locations.getJSONObject(it).getString("country_code") }.distinct()
        } catch (e: Exception) { status = error(e) }
    }
    Dialog(onDismissRequest = onDismiss, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
            Column(Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing)) {
                Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(stringResource(R.string.fox_title), style = MaterialTheme.typography.headlineSmall, modifier = Modifier.padding(vertical = 12.dp))
                    TextButton(onClick = onDismiss) { Text(stringResource(android.R.string.cancel)) }
                }
                Column(Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()).padding(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                    Icon(painterResource(R.drawable.ic_fox_24dp), contentDescription = null, modifier = Modifier.size(36.dp), tint = MaterialTheme.colorScheme.primary)
                    Text(stringResource(R.string.fox_hint))
                    Box {
                        OutlinedButton(onClick = { expandedAccounts = true }, modifier = Modifier.fillMaxWidth(), enabled = !busy) { Text(current?.email ?: stringResource(R.string.fox_accounts)) }
                        DropdownMenu(expandedAccounts, { expandedAccounts = false }) { accounts.forEach { account -> DropdownMenuItem(text = { Text(account.email) }, onClick = { selected = account.id; country = account.country; expandedAccounts = false }) } }
                    }
                    Text(stringResource(if (signIn) R.string.fox_step_login else if (pending) R.string.fox_step_verify else R.string.fox_step_connect), style = MaterialTheme.typography.titleMedium)
                    if (current != null && !adding) TextButton(onClick = { adding = true; email = ""; code = ""; status = "" }, enabled = !busy) { Text(stringResource(R.string.fox_add_account)) }
                    if (adding && current != null) TextButton(onClick = { adding = false; password = "" }, enabled = !busy) { Text(stringResource(R.string.fox_back_accounts)) }
                    if (ready) current?.let { account ->
                        val max = account.info.optLong("quota_max", -1); val remaining = account.info.optLong("quota_remaining", -1)
                        Text(if (max >= 0 && remaining >= 0) (if (fa) "باقی‌مانده: " else "Remaining: ") + String.format("%.2f / %.2f GB", remaining / 1e9, max / 1e9) else stringResource(R.string.fox_quota_unknown))
                        val reset = account.info.optLong("quota_reset", 0)
                        if (reset in 1..253402300799L) Text((if (fa) "بازنشانی: " else "Reset: ") + DateFormat.getDateInstance().format(Date(reset * 1000)))
                    }
                    if (ready) Box {
                        OutlinedButton(onClick = { expandedCountries = true }, modifier = Modifier.fillMaxWidth(), enabled = !busy) { Text(stringResource(R.string.fox_location) + " · " + country) }
                        DropdownMenu(expandedCountries, { expandedCountries = false }) { countries.forEach { value -> DropdownMenuItem(text = { Text(value) }, onClick = { country = value; expandedCountries = false }) } }
                    }
                    if (signIn) {
                    OutlinedTextField(email, { email = it }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email, autoCorrectEnabled = false), label = { Text(stringResource(R.string.fox_email)) }, singleLine = true, modifier = Modifier.fillMaxWidth(), enabled = !busy)
                    OutlinedTextField(password, { password = it }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, autoCorrectEnabled = false), label = { Text(stringResource(R.string.fox_password)) }, singleLine = true, visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth(), enabled = !busy)
                    Button(onClick = { run { FoxAccounts.login(context, email, password).id } }, enabled = !busy && email.isNotBlank() && password.isNotBlank(), modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.fox_login)) }
                    }
                    if (pending && current != null) {
                        OutlinedTextField(code, { code = it.take(16) }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword, autoCorrectEnabled = false), label = { Text(stringResource(R.string.fox_code)) }, singleLine = true, modifier = Modifier.fillMaxWidth(), enabled = !busy)
                        Button(onClick = { run { FoxAccounts.verify(context, current.id, code).id.also { code = "" } } }, enabled = !busy && code.isNotBlank(), modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.fox_verify)) }
                    }
                    if (busy) LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
                    if (status.isNotBlank()) Text(status, color = MaterialTheme.colorScheme.primary)
                    if (ready) {
                    OutlinedButton(onClick = { current?.let { account -> run { account.country = country; FoxAccounts.save(context, account); FoxAccounts.refresh(context, account.id, true).id } } }, enabled = !busy && current != null && !current.pending, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.fox_refresh)) }
                    Button(onClick = {
                        current?.let { account ->
                            if (busy) return@Button
                            busy = true; status = waiting
                            scope.launch {
                                try {
                                    val guid = withContext(Dispatchers.IO) { account.country = country; FoxAccounts.save(context, account); FoxAccounts.sync(context, FoxAccounts.get(context, account.id)) }
                                    onChanged(); onConnect(guid); onDismiss()
                                } catch (e: Exception) { status = error(e) }
                                finally { busy = false }
                            }
                        }
                    }, enabled = !busy && current != null && !current.pending, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.fox_connect)) }
                    TextButton(onClick = { current?.let { account -> run { FoxAccounts.remove(context, account.id); null } } }, enabled = !busy && current != null, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.fox_remove)) }
                    }
                    Text(stringResource(R.string.fox_limits), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }
}
