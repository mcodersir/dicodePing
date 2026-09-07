package com.v2ray.ang.handler

import java.time.Instant

/** Public V2Ray share links only; Telegram/MTProto/SOCKS links are never candidates. */
object ServerPoolParser {
    private val links = Regex("(?i)\\b(?:vmess|vless|trojan|ss)://[^\\s<>\"'\\u200b-\\u200f]+")
    private val wrappers = Regex("""<div\b[^>]*\bclass\s*=\s*["'][^"']*\btgme_widget_message_wrap\b[^"']*["'][^>]*>""", RegexOption.IGNORE_CASE)
    private val dates = Regex("""\bdatetime\s*=\s*["']([^"']+)["']""", RegexOption.IGNORE_CASE)
    data class Extraction(val links: List<String>, val posts: Int, val datedPosts: Int, val newest: Instant?) {
        val summary: String get() = when {
            posts == 0 -> "صفحهٔ پیام‌های عمومی دریافت نشد"
            datedPosts == 0 -> "تاریخ پیام‌ها قابل خواندن نیست"
            links.isEmpty() -> "$posts پیام؛ بدون لینک مستقیم V2Ray"
            else -> "${links.size} کاندید از آخرین پیام‌های لینک‌دار · تاریخ ${newest.toString().take(10)}"
        }
    }
    fun channels(text: String): List<String> = text.lineSequence().map {
        it.trim().removePrefix("https://t.me/").removePrefix("http://t.me/").removePrefix("t.me/").removePrefix("@").trimEnd('/')
    }.filter { it.matches(Regex("[a-zA-Z][a-zA-Z0-9_]{3,31}")) }
        .distinctBy { it.lowercase() }.take(500).toList()

    fun inspect(html: String): Extraction {
        val result = linkedSetOf<String>()
        val posts = wrappers.split(html).drop(1)
        val dated = posts.mapNotNull { post ->
            val stamp = dates.find(post)?.groupValues?.get(1) ?: return@mapNotNull null
            runCatching { Instant.parse(stamp) }.getOrNull()?.let { it to post }
        }.sortedByDescending { it.first }
        var newest: Instant? = null
        for ((date, post) in dated) {
            // Keep href links and join inline formatting inside code blocks; br still separates links.
            val text = post.replace(Regex("(?i)</?(?:div|p|pre|li|code|time)\\b[^>]*>|<br\\s*/?>"), "\n")
                .replace(Regex("<[^>]+>"), "")
            val hrefs = Regex("""\bhref\s*=\s*["']([^"']+)["']""", RegexOption.IGNORE_CASE)
                .findAll(post).joinToString("\n") { it.groupValues[1] }
            val decoded = decodeEntities(hrefs + "\n" + text)
            links.findAll(decoded).forEach { if (result.add(it.value) && newest == null) newest = date }
            if (result.size >= 4) break
        }
        return Extraction(result.take(4), posts.size, dated.size, newest)
    }

    fun extract(html: String): List<String> = inspect(html).links

    private fun decodeEntities(text: String): String = Regex("&(#x[0-9a-fA-F]+|#[0-9]+|amp|quot|apos|lt|gt|nbsp);").replace(text) {
        when (val entity = it.groupValues[1]) {
            "amp" -> "&"; "quot" -> "\""; "apos" -> "'"; "lt" -> "<"; "gt" -> ">"; "nbsp" -> " "
            else -> {
                val code = if (entity.startsWith("#x")) entity.drop(2).toIntOrNull(16) else entity.drop(1).toIntOrNull()
                if (code != null && Character.isValidCodePoint(code)) String(Character.toChars(code)) else it.value
            }
        }
    }

    fun accepts(samples: List<Long>): Boolean = samples.size == 3 && samples.all { it in 1..900 }
}
