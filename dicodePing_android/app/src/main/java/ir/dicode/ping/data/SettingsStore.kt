package ir.dicode.ping.data

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

class SettingsStore(context: Context) {
    private val prefs = context.getSharedPreferences("dicodeping", Context.MODE_PRIVATE)

    var language: String
        get() = prefs.getString("language", "fa") ?: "fa"
        set(value) = prefs.edit().putString("language", value).apply()
    var theme: String
        get() = prefs.getString("theme", "dark") ?: "dark"
        set(value) = prefs.edit().putString("theme", value).apply()
    var connectionMode: String
        get() = prefs.getString("connection_mode", "auto") ?: "auto"
        set(value) = prefs.edit().putString("connection_mode", value).apply()
    var selectedServerId: String
        get() = prefs.getString("selected_server", "") ?: ""
        set(value) = prefs.edit().putString("selected_server", value).apply()
    var bypassDomains: String
        get() = prefs.getString("bypass_domains", "") ?: ""
        set(value) = prefs.edit().putString("bypass_domains", value).apply()
    var bypassApps: Set<String>
        get() = prefs.getStringSet("bypass_apps", emptySet())?.toSet().orEmpty()
        set(value) = prefs.edit().putStringSet("bypass_apps", value.toSet()).apply()

    // v1.7.0-rc.2: per-app VPN settings.
    var perAppVpnMode: String
        get() = prefs.getString("per_app_vpn_mode", "disabled") ?: "disabled"
        set(value) = prefs.edit().putString("per_app_vpn_mode", value).apply()
    var perAppVpnPackages: Set<String>
        get() = prefs.getStringSet("per_app_vpn_packages", emptySet())?.toSet().orEmpty()
        set(value) = prefs.edit().putStringSet("per_app_vpn_packages", value.toSet()).apply()

    // v1.7.0-rc.2: VPN sharing settings.
    var vpnSharingUsb: Boolean
        get() = prefs.getBoolean("vpn_sharing_usb", false)
        set(value) = prefs.edit().putBoolean("vpn_sharing_usb", value).apply()
    var vpnSharingHotspot: Boolean
        get() = prefs.getBoolean("vpn_sharing_hotspot", false)
        set(value) = prefs.edit().putBoolean("vpn_sharing_hotspot", value).apply()

    // v1.7.0-rc.2: CDN formatting settings.
    var cdnFormattingEnabled: Boolean
        get() = prefs.getBoolean("cdn_formatting_enabled", false)
        set(value) = prefs.edit().putBoolean("cdn_formatting_enabled", value).apply()
    var cdnFormattingDomain: String
        get() = prefs.getString("cdn_formatting_domain", "speed.cloudflare.com") ?: "speed.cloudflare.com"
        set(value) = prefs.edit().putString("cdn_formatting_domain", value).apply()
    var lastServerRefreshAt: Long
        get() = prefs.getLong("last_server_refresh_at", 0L)
        set(value) = prefs.edit().putLong("last_server_refresh_at", value).apply()
    var diagnosticLogging: Boolean
        get() = prefs.getBoolean("diagnostic_logging", false)
        set(value) = prefs.edit().putBoolean("diagnostic_logging", value).apply()
    var sourceRevisions: Map<String, String>
        get() = runCatching {
            val json = JSONObject(prefs.getString("source_revisions", "{}") ?: "{}")
            json.keys().asSequence().associateWith { json.optString(it) }
        }.getOrDefault(emptyMap())
        set(value) {
            val json = JSONObject(); value.forEach { (id, revision) -> json.put(id, revision) }
            prefs.edit().putString("source_revisions", json.toString()).apply()
        }

    fun isServerRefreshDue(now: Long = System.currentTimeMillis()): Boolean {
        if (loadServers().isEmpty()) return true
        val last = lastServerRefreshAt
        return last <= 0L || now - last >= SERVER_REFRESH_INTERVAL_MS
    }

    fun loadSources(): MutableList<SourceDefinition> {
        val raw = prefs.getString("sources", null)
        val list = mutableListOf<SourceDefinition>()
        if (!raw.isNullOrBlank()) runCatching {
            val arr = JSONArray(raw)
            for (i in 0 until arr.length()) list += SourceDefinition.fromJson(arr.getJSONObject(i))
        }
        val default = list.firstOrNull { it.isDefault || it.id == "default" }
        if (default == null) list.add(0, defaultSource(language))
        else {
            default.enabled = true
            default.name = default.name.ifBlank { if (language == "en") "Primary source" else "منبع اصلی" }
        }
        list.sortBy { it.order }
        list.forEachIndexed { i, s -> s.order = i }
        return list
    }

    fun saveSources(sources: List<SourceDefinition>) {
        val arr = JSONArray()
        sources.sortedBy { it.order }.forEach { arr.put(it.toJson()) }
        prefs.edit().putString("sources", arr.toString()).apply()
    }

    fun loadServers(): List<ServerRecord> {
        val raw = prefs.getString("servers", "[]") ?: "[]"
        return runCatching {
            val arr = JSONArray(raw)
            List(arr.length()) { ServerRecord.fromJson(arr.getJSONObject(it)) }
        }.getOrDefault(emptyList())
    }

    fun saveServers(servers: List<ServerRecord>) {
        val arr = JSONArray(); servers.forEach { arr.put(it.toJson()) }
        prefs.edit().putString("servers", arr.toString()).apply()
    }

    companion object {
        const val DEFAULT_URL = "https://raw.githubusercontent.com/mcodersir/DicodeConfigChecker/refs/heads/main/sub.txt"
        val SERVER_REFRESH_INTERVAL_MS: Long = TimeUnit.DAYS.toMillis(2)

        fun defaultSource(language: String = "fa") = SourceDefinition(
            "default",
            if (language == "en") "Primary source" else "منبع اصلی",
            DEFAULT_URL,
            0,
            true,
            true,
        )

        fun idForUrl(url: String): String {
            val hash = MessageDigest.getInstance("SHA-256").digest(url.trim().toByteArray())
            return "src-" + hash.take(6).joinToString("") { "%02x".format(it) }
        }
    }
}
