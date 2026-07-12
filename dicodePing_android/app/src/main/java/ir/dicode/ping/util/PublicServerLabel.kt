package ir.dicode.ping.util

object PublicServerLabel {
    private val protocolWords = Regex(
        pattern = "(?i)(?<![a-z0-9])(vless|vmess|trojan|shadowsocks|socks5?|http2?|hysteria2?|hy2|tuic|wireguard|xray|xhttp|grpc|websocket|ws|tcp|kcp|quic|reality|tls|xtls|h2)(?![a-z0-9])",
    )
    private val separators = Regex("[\\s•|/_+\\-:]+")

    fun name(raw: String, fallback: String = "Server"): String {
        val cleaned = raw
            .replace(protocolWords, " ")
            .replace(Regex("(?i)(?<![a-z0-9])ss://"), " ")
            .replace(Regex("[()\\[\\]{}]+"), " ")
            .replace(separators, " ")
            .trim(' ', '•', '|', '/', '_', '-', ':')
            .trim()
        return cleaned.ifBlank { fallback.ifBlank { "Server" } }
    }
}
