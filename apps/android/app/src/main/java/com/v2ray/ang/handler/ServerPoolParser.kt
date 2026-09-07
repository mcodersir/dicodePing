package com.v2ray.ang.handler

import java.time.Instant

/** Public V2Ray share links only; Telegram/MTProto/SOCKS links are never candidates. */
object ServerPoolParser {
    private val links = Regex("(?i)\\b(?:vmess|vless|trojan|ss)://[^\\s<>\"'`\\u200b-\\u200f]+")
    private val wrappers = Regex("""<div\b[^>]*\bclass\s*=\s*["'][^"']*\btgme_widget_message_wrap\b[^"']*["'][^>]*>""", RegexOption.IGNORE_CASE)
    private val dates = Regex("""\bdatetime\s*=\s*["']([^"']+)["']""", RegexOption.IGNORE_CASE)
    private val hrefs = Regex("""\bhref\s*=\s*["']([^"']+)["']""", RegexOption.IGNORE_CASE)
    data class Extraction(val links: List<String>, val posts: Int, val datedPosts: Int, val newest: Instant?) {
        val summary: String get() = when {
            links.isNotEmpty() && newest != null -> "${links.size} کاندید از آخرین پیام‌های قابل‌نمایش · تاریخ ${newest.toString().take(10)}"
            links.isNotEmpty() -> "${links.size} کاندید از آخرین پیام‌های قابل‌نمایش · تاریخ در HTML نبود"
            posts == 0 -> "صفحهٔ پیام‌های عمومی دریافت نشد"
            datedPosts == 0 -> "$posts پیام؛ بدون لینک مستقیم V2Ray · تاریخ در HTML نبود"
            else -> "$posts پیام؛ بدون لینک مستقیم V2Ray"
        }
    }
    fun channels(text: String): List<String> = text.lineSequence().map {
        it.trim().removePrefix("https://t.me/").removePrefix("http://t.me/").removePrefix("t.me/").removePrefix("@").trimEnd('/')
    }.filter { it.matches(Regex("[a-zA-Z][a-zA-Z0-9_]{3,31}")) }
        .distinctBy { it.lowercase() }.take(500).toList()

    fun inspect(html: String): Extraction {
        if (html.isBlank()) return Extraction(emptyList(), 0, 0, null)
        val posts = wrappers.split(html).drop(1)
        var datedPosts = 0
        var newest: Instant? = null
        val result = linkedSetOf<String>()

        fun addLinks(fragment: String): Boolean {
            val hrefValues = hrefs.findAll(fragment).joinToString("\n") { it.groupValues[1] }
            val text = fragment
                .replace(Regex("(?i)</?(?:div|p|pre|li|code|time|blockquote|section|article)\\b[^>]*>|<br\\s*/?>"), "\n")
                .replace(Regex("<[^>]+>"), "")
            val decoded = decodeEntities(hrefValues + "\n" + text).replace("\\u0026", "&", ignoreCase = true)
            links.findAll(decoded).toList().asReversed().forEach { match ->
                val value = match.value.trimEnd(')', ']', '}', ',', ';', '.', '،')
                if (value.isNotBlank()) result.add(value)
                if (result.size >= 4) return true
            }
            return false
        }

        for (post in posts.asReversed()) {
            val timestamp = dates.find(post)?.groupValues?.get(1)?.let {
                runCatching { Instant.parse(it) }.getOrNull()
            }
            if (timestamp != null) datedPosts++
            val countBefore = result.size
            val full = addLinks(post)
            if (result.size > countBefore && newest == null) newest = timestamp
            if (full) break
        }
        if (posts.isEmpty()) addLinks(html)
        val latest = result.take(4)
        val postCount = if (posts.isEmpty() && latest.isNotEmpty()) 1 else posts.size
        return Extraction(latest, postCount, datedPosts, newest)
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

    fun accepts(samples: List<Long>, requiredRounds: Int = 3): Boolean =
        requiredRounds in ServerPoolOptions.MIN_TEST_ROUNDS..ServerPoolOptions.MAX_TEST_ROUNDS &&
            samples.size == requiredRounds && samples.all { it in 1..900 }
}
