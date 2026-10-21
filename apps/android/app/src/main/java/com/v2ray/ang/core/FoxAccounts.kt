package com.v2ray.ang.core

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import android.util.Base64
import com.v2ray.ang.dto.entities.ProfileItem
import com.v2ray.ang.dto.entities.SubscriptionItem
import com.v2ray.ang.enums.EConfigType
import com.v2ray.ang.handler.MmkvManager
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.RandomAccessFile
import java.security.KeyStore
import java.util.UUID
import java.util.concurrent.TimeUnit
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import javax.net.ssl.TrustManagerFactory
import javax.net.ssl.X509TrustManager
import okhttp3.OkHttpClient
import okhttp3.Request
import java.net.Proxy
import java.net.InetSocketAddress
import kotlin.concurrent.thread

internal class FoxError(val code: String, message: String) : Exception(message)
internal data class FoxAccount(val id: String, var country: String, var state: JSONObject, var info: JSONObject) {
    val email: String get() = state.optString("email")
    val pending: Boolean get() = state.optString("session_token").isNotBlank()
    fun json() = JSONObject().put("id", id).put("country", country).put("state", state).put("info", info)
}
internal data class FoxProfile(val accountId: String, val country: String)
internal object FoxAccounts {
    const val LOCAL_PORT = 7854
    const val SHARE_URI = "socks5://127.0.0.1:7854#Firefox-VPN"
    private const val KEY = "dicode.fox.accounts.v1"
    private val lock = Any()
    private fun file(context: Context) = AtomicFile(File(context.noBackupFilesDir, "fox-accounts.enc"))
    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        if (store.containsAlias(KEY)) return store.getKey(KEY, null) as SecretKey
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(KEY, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).setKeySize(256).build())
        }.generateKey()
    }
    private fun <T> locked(context: Context, work: () -> T): T = synchronized(lock) {
        RandomAccessFile(File(context.noBackupFilesDir, "fox-accounts.lock"), "rw").use { file -> file.channel.use { channel -> channel.lock().use { work() } } }
    }
    fun list(context: Context): List<FoxAccount> = locked(context) { read(context) }
    private fun read(context: Context): List<FoxAccount> {
        val storage = file(context)
        if (!storage.baseFile.exists()) return emptyList()
        val encrypted = storage.openRead().use { it.readBytes() }
        require(encrypted.size >= 28)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, encrypted.copyOfRange(0, 12))) }
        val clear = cipher.doFinal(encrypted.copyOfRange(12, encrypted.size))
        try {
            val array = JSONArray(clear.toString(Charsets.UTF_8))
            return (0 until array.length()).map { val item = array.getJSONObject(it); FoxAccount(item.getString("id"), item.optString("country", "REC"), item.getJSONObject("state"), item.optJSONObject("info") ?: JSONObject()) }
        } finally { clear.fill(0) }
    }
    private fun write(context: Context, all: List<FoxAccount>) {
        val clear = JSONArray().apply { all.forEach { put(it.json()) } }.toString().toByteArray()
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
        val storage = file(context); val stream = storage.startWrite()
        try { stream.write(cipher.iv); stream.write(cipher.doFinal(clear)); storage.finishWrite(stream) }
        catch (e: Exception) { storage.failWrite(stream); throw e }
        finally { clear.fill(0) }
    }
    fun save(context: Context, account: FoxAccount, create: Boolean = false) = locked(context) {
        val all = read(context).toMutableList()
        if (!create && all.none { it.id == account.id }) return@locked
        all.removeAll { it.id == account.id }; all.add(account); write(context, all)
    }
    fun get(context: Context, id: String) = list(context).firstOrNull { it.id == id } ?: throw FoxError("login_required", "Sign in to the Fox account for this profile")
    fun updateSession(context: Context, id: String, state: JSONObject, info: JSONObject? = null) = locked(context) {
        val all = read(context); val current = all.firstOrNull { it.id == id } ?: return@locked
        current.state = state; if (info != null) current.info = info; write(context, all)
    }
    fun remove(context: Context, id: String) = locked(context) {
        MmkvManager.getSelectServer()?.let { guid -> if (MmkvManager.decodeServerRaw(guid)?.let(::profile)?.accountId == id) LauncherManager.stopService(context) }
        write(context, read(context).filter { it.id != id })
        MmkvManager.decodeSubscriptions().filter { it.subscription.url == "dicode-fox://$id" }.forEach { MmkvManager.removeSubscription(it.guid) }
    }
    fun roots(): String {
        val trust = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm()).apply { init(null as KeyStore?) }
        return trust.trustManagers.filterIsInstance<X509TrustManager>().flatMap { it.acceptedIssuers.toList() }.joinToString("\n") {
            "-----BEGIN CERTIFICATE-----\n" + Base64.encodeToString(it.encoded, Base64.NO_WRAP).chunked(64).joinToString("\n") + "\n-----END CERTIFICATE-----"
        }
    }
    fun request(context: Context, request: JSONObject): JSONObject = FoxProcess(context).use { it.execute(request) }
    fun login(context: Context, email: String, password: String): FoxAccount {
        val result = request(context, JSONObject().put("operation", "login").put("email", email.trim()).put("password", password))
        val account = list(context).firstOrNull { it.email.equals(email.trim(), true) } ?: FoxAccount(UUID.randomUUID().toString().replace("-", ""), "REC", JSONObject(), JSONObject())
        account.state = result.getJSONObject("state"); save(context, account, create = true)
        if (!account.pending) refresh(context, account.id, true)
        return get(context, account.id)
    }
    fun verify(context: Context, id: String, code: String): FoxAccount {
        val account = get(context, id)
        val result = request(context, JSONObject().put("operation", "verify").put("code", code.trim()).put("state", account.state))
        account.state = result.getJSONObject("state"); save(context, account); return refresh(context, id, true)
    }
    fun refresh(context: Context, id: String, syncProfile: Boolean): FoxAccount {
        val account = get(context, id)
        val result = request(context, JSONObject().put("operation", "status").put("state", account.state))
        account.state = result.getJSONObject("state"); account.info = result.optJSONObject("account") ?: JSONObject(); save(context, account)
        if (syncProfile) sync(context, get(context, id))
        return account
    }
    fun resolveProfile(context: Context, node: ProfileItem?): FoxProfile? {
        profile(node)?.let { return it }
        if (node?.configType != EConfigType.SOCKS || node.server != "127.0.0.1"
            || node.serverPort != LOCAL_PORT.toString() || !node.username.isNullOrEmpty() || !node.password.isNullOrEmpty()) return null
        val accounts = list(context).filterNot { it.pending }
        val url = MmkvManager.decodeSubscriptions().firstOrNull { it.guid == node.subscriptionId }?.subscription?.url
        val account = accounts.firstOrNull { url == "dicode-fox://${it.id}" } ?: accounts.singleOrNull() ?: return null
        return FoxProfile(account.id, account.country)
    }
    fun profile(node: ProfileItem?): FoxProfile? {
        val id = node?.foxAccountId ?: return null
        val country = node.foxCountry ?: "REC"
        if (!id.matches(Regex("[a-fA-F0-9]{32}")) || !(country == "REC" || country.matches(Regex("[A-Za-z]{2}")))
            || node.configType != EConfigType.SOCKS || node.server != "127.0.0.1" || node.serverPort != LOCAL_PORT.toString())
            throw FoxError("input", "Invalid managed Fox SOCKS profile")
        return FoxProfile(id, country.uppercase(java.util.Locale.ROOT))
    }
    fun profile(raw: String): FoxProfile? {
        val json = runCatching { JSONObject(raw) }.getOrNull() ?: return null
        if (!json.has("dicodeFox")) return null
        val fox = json.optJSONObject("dicodeFox") ?: throw FoxError("input", "Invalid Fox profile; recreate it from the Fox page")
        val id = fox.optString("accountId"); val country = fox.optString("country", "REC")
        if (!id.matches(Regex("[a-fA-F0-9]{32}")) || !(country == "REC" || country.matches(Regex("[A-Za-z]{2}")))) throw FoxError("input", "Invalid Fox profile metadata")
        return FoxProfile(id, country.uppercase(java.util.Locale.ROOT))
    }
    fun template(id: String, country: String): String = JSONObject()
        .put("dicodeFox", JSONObject().put("accountId", id).put("country", country))
        .put("inbounds", JSONArray())
        .put("outbounds", JSONArray().put(JSONObject().put("tag", "proxy").put("protocol", "socks").put("settings", JSONObject().put("servers", JSONArray().put(JSONObject().put("address", "127.0.0.1").put("port", 1080)))))).toString()
    fun updateQuota(context: Context, id: String, info: JSONObject? = null) {
        val account = locked(context) {
            val all = read(context); val current = all.firstOrNull { it.id == id } ?: return@locked null
            if (info != null) { current.info = info; write(context, all) }
            current
        } ?: return
        val cache = MmkvManager.decodeSubscriptions().firstOrNull { it.subscription.url == "dicode-fox://$id" } ?: return
        applyQuota(cache.subscription, account)
        MmkvManager.encodeSubscription(cache.guid, cache.subscription)
        com.v2ray.ang.helper.MessageHelper.sendMsg2UI(context, com.v2ray.ang.AppConfig.MSG_SERVERS_CHANGED, "")
    }
    private fun applyQuota(sub: SubscriptionItem, account: FoxAccount) {
        sub.totalBytes = account.info.optLong("quota_max", 0)
        val remaining = account.info.optLong("quota_remaining", -1)
        sub.uploadBytes = 0
        sub.downloadBytes = if (remaining >= 0 && sub.totalBytes > 0) (sub.totalBytes - remaining).coerceIn(0, sub.totalBytes) else 0
        sub.lastUpdated = System.currentTimeMillis()
    }
    fun sync(context: Context, account: FoxAccount): String {
        val cache = MmkvManager.decodeSubscriptions().firstOrNull { it.subscription.url == "dicode-fox://${account.id}" }
        val sub = cache?.subscription ?: SubscriptionItem(remarks = "${context.getString(com.v2ray.ang.R.string.fox_title)} · ${account.email}", url = "dicode-fox://${account.id}", autoUpdate = false)
        applyQuota(sub, account); val group = MmkvManager.encodeSubscription(cache?.guid.orEmpty(), sub)
        val nodes = MmkvManager.decodeServerList(group); val guid = nodes.firstOrNull().orEmpty()
        val node = ProfileItem(configType = EConfigType.SOCKS, server = "127.0.0.1", serverPort = LOCAL_PORT.toString(),
            foxAccountId = account.id, foxCountry = account.country, subscriptionId = group, remarks = "${context.getString(com.v2ray.ang.R.string.fox_title)} · Firefox VPN · ${account.country}")
        val stored = MmkvManager.encodeServerConfigWithRaw(guid, node, template(account.id, account.country))
        nodes.drop(1).forEach(MmkvManager::removeServer)
        return stored
    }
}

/** Private stdin/stdout protocol. Tokens never reach logcat or process arguments. */
internal class FoxProcess(private val context: Context) : AutoCloseable {
    @Volatile private var process: Process? = null
    val isAlive: Boolean get() = process?.isAlive == true
    @Volatile private var stopped = false
    private fun launch(request: JSONObject): java.io.BufferedReader {
        val executable = File(context.applicationInfo.nativeLibraryDir, "libdicodefox.so")
        check(executable.isFile && executable.canExecute()) { "Fox helper is missing; install the full DicodePing APK" }
        val command = ProcessBuilder(executable.absolutePath).directory(context.cacheDir)
        listOf("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy").forEach { command.environment().remove(it) }
        check(!stopped) { "Fox start cancelled" }
        val child = command.start(); process = child
        if (stopped) { child.destroy(); error("Fox start cancelled") }
        thread(isDaemon = true, name = "FoxPrivateErrors") { runCatching { child.errorStream.bufferedReader().useLines { lines -> lines.forEach { } } } }
        request.put("ca_bundle", FoxAccounts.roots())
        child.outputStream.bufferedWriter().apply { write(request.toString()); newLine(); flush() }
        return child.inputStream.bufferedReader()
    }
    private fun response(reader: java.io.BufferedReader): JSONObject {
        val child = process!!
        val timer = thread(isDaemon = true) { try { Thread.sleep(100000); child.destroyForcibly() } catch (_: InterruptedException) { } }
        try {
            val result = JSONObject(reader.readLine() ?: "{}")
            if (!result.optBoolean("ok")) throw FoxError(result.optString("error", "helper"), result.optString("message", "Fox helper did not start"))
            return result
        } finally { timer.interrupt() }
    }
    fun execute(request: JSONObject): JSONObject = launch(request).use { response(it) }
    fun start(id: String, country: String, port: Int, onExit: (() -> Unit)? = null) {
        val account = FoxAccounts.get(context, id)
        val reader = launch(JSONObject().put("operation", "serve").put("state", account.state).put("country", country).put("listen", "127.0.0.1:$port"))
        val result = response(reader)
        FoxAccounts.updateSession(context, id, result.getJSONObject("state"), result.optJSONObject("account"))
        java.net.Socket().use { socket ->
            socket.connect(InetSocketAddress("127.0.0.1", port), 3000); socket.soTimeout = 3000
            socket.getOutputStream().write(byteArrayOf(5, 1, 0)); socket.getOutputStream().flush()
            val input = java.io.DataInputStream(socket.getInputStream())
            if (input.readUnsignedByte() != 5 || input.readUnsignedByte() != 0) throw FoxError("helper", "Fox SOCKS handshake failed")
        }
        FoxAccounts.updateQuota(context, id)
        thread(isDaemon = true, name = "FoxSessionEvents") {
            runCatching { reader.useLines { lines -> lines.forEach { line ->
                val event = JSONObject(line)
                if (event.optString("event") == "state") { FoxAccounts.updateSession(context, id, event.getJSONObject("state")) }
                if (event.optString("event") == "quota") { FoxAccounts.updateQuota(context, id, event.getJSONObject("account")) }
            } } }
            runCatching { process?.waitFor() }; if (!stopped) onExit?.invoke()
        }
    }
    fun measure(port: Int, url: String): Long = AetherDelayTester.requestDelay(port, url)

    fun cancel() { stopped = true; process?.destroy() }

    override fun close() { stopped = true; process?.let { child -> runCatching { child.outputStream.close() }; child.destroy(); if (!child.waitFor(2, TimeUnit.SECONDS)) { child.destroyForcibly(); child.waitFor(2, TimeUnit.SECONDS) } }; process = null }
}
