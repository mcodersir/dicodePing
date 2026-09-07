package com.v2ray.ang.handler

import java.time.Instant

/** Public V2Ray share links only; Telegram/MTProto/SOCKS links are never candidates. */
object ServerPoolParser {
    private val links = Regex("(?i)\\b(?:vmess|vless|trojan|ss)://[^\\s<>\"'\\u200b-\\u200f]+")
    fun channels(text: String): List<String> = text.lineSequence().map {
        it.trim().removePrefix("https://t.me/").removePrefix("http://t.me/").removePrefix("t.me/").removePrefix("@").trimEnd('/')
    }.filter { it.matches(Regex("[a-zA-Z][a-zA-Z0-9_]{3,31}")) }
        .distinctBy { it.lowercase() }.take(500).toList()

    fun extract(html: String, now: Instant = Instant.now()): List<String> {
        val result = linkedSetOf<String>()
        for (post in html.split("<div class=\"tgme_widget_message_wrap").drop(1).asReversed()) {
            val stamp = Regex("datetime=\"([^\"]+)\"").find(post)?.groupValues?.get(1) ?: continue
            val date = runCatching { Instant.parse(stamp) }.getOrNull() ?: continue
            if (date.isBefore(now.minusSeconds(7 * 86400)) || date.isAfter(now.plusSeconds(300))) continue
            val decoded = post.replace("&amp;", "&").replace("&quot;", "\"")
                .replace("&#39;", "'").replace("&lt;", "<").replace("&gt;", ">")
            links.findAll(decoded).forEach { result.add(it.value) }
            if (result.size >= 4) break
        }
        return result.take(4)
    }

    fun accepts(samples: List<Long>): Boolean = samples.size == 3 && samples.all { it in 1..900 }
}
