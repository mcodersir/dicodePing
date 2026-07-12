package ir.dicode.ping.net

import android.net.Uri
import android.util.Base64
import ir.dicode.ping.data.ParsedNode
import org.json.JSONArray
import org.json.JSONObject
import java.net.URLDecoder
import java.nio.charset.StandardCharsets

object ConfigParser {
    private val regex = Regex("(?:vless|vmess|trojan|ss)://[^\\s<>\\\"']+", RegexOption.IGNORE_CASE)

    fun decodeSubscription(input: String): List<String> {
        var text = input.trim().removePrefix("\\uFEFF")
        if (!text.take(1000).contains("://")) {
            decodeBase64(text.filterNot(Char::isWhitespace))?.let { if (it.contains("://")) text = it }
        }
        return regex.findAll(Uri.decode(text)).map { it.value.trimEnd(')', ']', '}', '"', '\'', '>', '،', ',', '.', ';') }
            .distinctBy(::normalizeKey).toList()
    }

    fun parse(raw: String): ParsedNode? = runCatching {
        when {
            raw.startsWith("vless://", true) -> parseVlessOrTrojan(raw, "vless")
            raw.startsWith("trojan://", true) -> parseVlessOrTrojan(raw, "trojan")
            raw.startsWith("vmess://", true) -> parseVmess(raw)
            raw.startsWith("ss://", true) -> parseShadowsocks(raw)
            else -> null
        }
    }.getOrNull()

    private fun parseVlessOrTrojan(raw: String, protocol: String): ParsedNode? {
        val uri = Uri.parse(raw)
        val host = uri.host ?: return null
        val port = if (uri.port > 0) uri.port else 443
        val credential = Uri.decode(uri.encodedUserInfo.orEmpty()).substringBefore(':').ifBlank { return null }
        val q = uri.queryParameterNames.associateWith { uri.getQueryParameter(it).orEmpty() }
        val name = Uri.decode(uri.fragment ?: "").ifBlank { "${protocol.uppercase()} • $host" }
        val stream = buildStream(q)
        val settings = if (protocol == "vless") JSONObject().put("vnext", JSONArray().put(
            JSONObject().put("address", host).put("port", port).put("users", JSONArray().put(
                JSONObject().put("id", credential).put("encryption", q["encryption"].orEmpty().ifBlank { "none" })
                    .apply { q["flow"]?.takeIf { it.isNotBlank() }?.let { put("flow", it) } }.put("level", 8)
            ))
        )) else JSONObject().put("servers", JSONArray().put(
            JSONObject().put("address", host).put("port", port).put("password", credential)
                .apply { q["flow"]?.takeIf { it.isNotBlank() }?.let { put("flow", it) } }.put("level", 8)
        ))
        val outbound = JSONObject().put("tag", "proxy").put("protocol", protocol).put("settings", settings)
            .put("streamSettings", stream).put("mux", JSONObject().put("enabled", false))
        return ParsedNode(raw, protocol, name, host, port, outbound)
    }

    private fun parseVmess(raw: String): ParsedNode? {
        val obj = JSONObject(decodeBase64(raw.substringAfter("vmess://")) ?: return null)
        val host = obj.optString("add").ifBlank { obj.optString("address") }
        val port = obj.optString("port", "443").toIntOrNull() ?: 443
        val user = JSONObject().put("id", obj.optString("id")).put("alterId", obj.optInt("aid", 0))
            .put("security", obj.optString("scy", obj.optString("security", "auto"))).put("level", 8)
        val settings = JSONObject().put("vnext", JSONArray().put(
            JSONObject().put("address", host).put("port", port).put("users", JSONArray().put(user))
        ))
        val q = mutableMapOf<String, String>()
        q["type"] = obj.optString("net", "tcp"); q["security"] = obj.optString("tls", "none")
        q["host"] = obj.optString("host"); q["path"] = obj.optString("path"); q["sni"] = obj.optString("sni")
        q["alpn"] = obj.optString("alpn"); q["fp"] = obj.optString("fp"); q["headerType"] = obj.optString("type")
        val outbound = JSONObject().put("tag", "proxy").put("protocol", "vmess").put("settings", settings)
            .put("streamSettings", buildStream(q)).put("mux", JSONObject().put("enabled", false))
        return ParsedNode(raw, "vmess", obj.optString("ps").ifBlank { "VMess • $host" }, host, port, outbound)
    }

    private fun parseShadowsocks(raw: String): ParsedNode? {
        val withoutFragment = raw.substringBefore('#')
        var body = withoutFragment.substringAfter("ss://")
        if (body.contains('?')) body = body.substringBefore('?')
        var decoded = Uri.decode(body)
        if (!decoded.contains('@')) decoded = decodeBase64(decoded) ?: return null
        val userAndHost = decoded.split('@', limit = 2)
        if (userAndHost.size != 2) return null
        var user = userAndHost[0]
        if (!user.contains(':')) user = decodeBase64(user) ?: return null
        val method = user.substringBefore(':'); val password = user.substringAfter(':')
        val hp = userAndHost[1]
        val host = if (hp.startsWith("[")) hp.substringAfter('[').substringBefore(']') else hp.substringBeforeLast(':')
        val port = hp.substringAfterLast(':').toIntOrNull() ?: return null
        val settings = JSONObject().put("servers", JSONArray().put(
            JSONObject().put("address", host).put("port", port).put("method", method).put("password", password).put("level", 8)
        ))
        val outbound = JSONObject().put("tag", "proxy").put("protocol", "shadowsocks").put("settings", settings)
        val name = Uri.decode(raw.substringAfter('#', "")).ifBlank { "Shadowsocks • $host" }
        return ParsedNode(raw, "ss", name, host, port, outbound)
    }

    private fun buildStream(q: Map<String, String>): JSONObject {
        var network = q["type"].orEmpty().ifBlank { q["net"].orEmpty().ifBlank { "tcp" } }
        if (network.equals("splithttp", true)) network = "xhttp"
        val stream = JSONObject().put("network", network)
        val security = q["security"].orEmpty().ifBlank { "none" }
        if (security != "none") {
            stream.put("security", security)
            val sni = q["sni"].orEmpty().ifBlank { q["serverName"].orEmpty() }
            val fp = q["fp"].orEmpty().ifBlank { q["fingerprint"].orEmpty() }
            if (security == "tls") {
                val tls = JSONObject().put("allowInsecure", q["allowInsecure"] in listOf("1", "true"))
                if (sni.isNotBlank()) tls.put("serverName", sni)
                if (fp.isNotBlank()) tls.put("fingerprint", fp)
                q["alpn"]?.takeIf { it.isNotBlank() }?.let { tls.put("alpn", JSONArray(it.split(',').map { item -> item.trim() })) }
                stream.put("tlsSettings", tls)
            } else if (security == "reality") {
                val reality = JSONObject()
                if (sni.isNotBlank()) reality.put("serverName", sni)
                if (fp.isNotBlank()) reality.put("fingerprint", fp)
                q["pbk"]?.let { reality.put("publicKey", it) }; q["sid"]?.let { reality.put("shortId", it) }
                q["spx"]?.let { reality.put("spiderX", Uri.decode(it)) }
                stream.put("realitySettings", reality)
            }
        }
        val host = q["host"].orEmpty(); val path = Uri.decode(q["path"].orEmpty().ifBlank { q["serviceName"].orEmpty() })
        when (network.lowercase()) {
            "ws" -> stream.put("wsSettings", JSONObject().apply { if (path.isNotBlank()) put("path", path); if (host.isNotBlank()) put("host", host) })
            "grpc" -> stream.put("grpcSettings", JSONObject().apply { if (path.isNotBlank()) put("serviceName", path); if (q["mode"] == "multi") put("multiMode", true) })
            "httpupgrade" -> stream.put("httpupgradeSettings", JSONObject().apply { if (path.isNotBlank()) put("path", path); if (host.isNotBlank()) put("host", host) })
            "xhttp" -> stream.put("xhttpSettings", JSONObject().apply { if (path.isNotBlank()) put("path", path); if (host.isNotBlank()) put("host", host); q["mode"]?.takeIf(String::isNotBlank)?.let { put("mode", it) } })
            "kcp" -> stream.put("kcpSettings", JSONObject().put("header", JSONObject().put("type", q["headerType"].orEmpty().ifBlank { "none" })))
        }
        return stream
    }

    private fun decodeBase64(value: String): String? = runCatching {
        val normalized = value.trim().replace('-', '+').replace('_', '/').let { it + "=".repeat((4 - it.length % 4) % 4) }
        String(Base64.decode(normalized, Base64.DEFAULT), StandardCharsets.UTF_8)
    }.getOrNull()

    private fun normalizeKey(raw: String): String = raw.substringBefore('#')
}
