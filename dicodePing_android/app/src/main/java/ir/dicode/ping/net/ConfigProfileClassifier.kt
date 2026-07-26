package ir.dicode.ping.net

import java.net.URLDecoder

/**
 * Conservative display hints based only on a config's own remark/hostname.
 * UNKNOWN is intentional: no quota or lifetime is invented.
 */
object ConfigProfileClassifier {
    enum class Tag { WORKER, LIMITED, PERSISTENT, UNKNOWN }

    fun classify(raw: String, host: String = ""): Tag {
        val text = runCatching { URLDecoder.decode(raw, Charsets.UTF_8.name()) }
            .getOrDefault(raw)
            .lowercase()
        val hostname = host.lowercase()
        if (
            hostname.endsWith(".workers.dev") ||
            hostname.endsWith(".pages.dev") ||
            "cloudflare worker" in text ||
            Regex("\\bworkers?\\b").containsMatchIn(text)
        ) return Tag.WORKER
        if (
            Regex("\\d+(?:[.,]\\d+)?\\s*(gb|mb|tb)\\b").containsMatchIn(text) ||
            listOf("quota", "volume", "limited", "حجمی", "حجم").any { it in text }
        ) return Tag.LIMITED
        if (listOf("permanent", "unlimited", "دائمی", "نامحدود").any { it in text }) {
            return Tag.PERSISTENT
        }
        return Tag.UNKNOWN
    }
}
