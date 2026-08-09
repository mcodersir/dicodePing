package ir.dicode.ping.net

import android.net.Uri

data class ConfigSecurityAssessment(
    val score: Int,
    val level: String,
    val labelFa: String,
    val labelEn: String,
)

/** Display-only estimate; this is not a cryptographic audit of the server. */
object ConfigSecurityRating {
    fun assess(raw: String, host: String = ""): ConfigSecurityAssessment {
        val uri = runCatching { Uri.parse(raw.trim()) }.getOrNull()
        val scheme = uri?.scheme.orEmpty().lowercase()
        fun q(vararg names: String): String = names.asSequence()
            .mapNotNull { runCatching { uri?.getQueryParameter(it) }.getOrNull() }
            .firstOrNull { !it.isNullOrBlank() }
            .orEmpty().lowercase()
        val security = q("security", "tls")
        val transport = q("type", "net", "network")
        val sni = q("sni", "serverName", "servername", "host")
        val insecure = q("allowInsecure", "insecure", "skip-cert-verify") in setOf("1", "true", "yes", "on")

        var score = 48
        when {
            security == "reality" -> score += 34
            security in setOf("tls", "xtls") -> score += 27
            scheme in setOf("trojan", "hysteria2", "hy2", "tuic") -> score += 23
            scheme in setOf("ss", "shadowsocks") -> score += 12
            else -> score -= 18
        }
        if (sni.isNotBlank() || (host.isNotBlank() && !looksLikeIp(host))) score += 7
        if (transport in setOf("ws", "grpc", "httpupgrade", "splithttp", "xhttp", "h2", "quic")) score += 4
        if (insecure) score -= 24
        if (scheme == "vmess") score -= 5
        if (scheme in setOf("http", "socks")) score -= 28
        score = score.coerceIn(10, 96)
        return when {
            score >= 78 -> ConfigSecurityAssessment(score, "high", "امنیت خوب", "Good security")
            score >= 55 -> ConfigSecurityAssessment(score, "standard", "امنیت معمولی", "Standard security")
            else -> ConfigSecurityAssessment(score, "basic", "امنیت پایه", "Basic security")
        }
    }

    private fun looksLikeIp(value: String): Boolean =
        value.trim().removePrefix("[").removeSuffix("]").let { candidate ->
            candidate.contains(":") || candidate.split('.').let { parts ->
                parts.size == 4 && parts.all { it.toIntOrNull() in 0..255 }
            }
        }
}
