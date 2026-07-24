package ir.dicode.ping.util

object PublicServerLabel {
    fun name(raw: String, fallback: String = "Server"): String = raw
        .replace(Regex("[\\u200e\\u200f\\u202a-\\u202e\\u2066-\\u2069]"), "")
        .replace(Regex("\\s+"), " ")
        .trim()
        .ifBlank { fallback.ifBlank { "Server" } }
}
