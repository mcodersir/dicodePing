package com.v2ray.ang.handler

import com.v2ray.ang.AppConfig
import com.v2ray.ang.dto.UrlContentRequest
import com.v2ray.ang.util.HttpUtil

/**
 * Merges exactly the two built-in Config Checker sources in priority order.
 * Sources are fetched in priority order; plain links are taken as-is and
 * base64 bodies are decoded. Results are deduplicated without dropping the second source.
 */
object PrimarySubscriptionSources {

    data class Source(val name: String, val url: String)

    val DEFAULT_SOURCES = listOf(
        Source("Dicode Config Checker", AppConfig.DICODE_PRIMARY_SUBSCRIPTION_URL),
        Source("Patterniha Free-Configs", AppConfig.DICODE_SECONDARY_SUBSCRIPTION_URL),
    )

    private val LINK_REGEX = Regex("(?:vmess|vless|trojan|ss|ssr|hysteria2?|hy2|tuic)://[^\\s\"'<>\\\\]+")

    fun aggregate(): String {
        val collected = LinkedHashSet<String>()
        for (source in DEFAULT_SOURCES) {
            try {
                val response = HttpUtil.getUrlContentResponseWithUserAgent(
                    UrlContentRequest(
                        url = source.url,
                        userAgent = "",
                        requestHeaders = null,
                        timeout = 12000,
                        httpPort = 0,
                        proxyUsername = "",
                        proxyPassword = "",
                    )
                )
                val body = response.content ?: continue
                for (link in extractLinks(body)) {
                            collected.add(link)
                }
            } catch (_: Exception) {
                // Best effort: a failed source is skipped.
            }
        }
        return collected.joinToString("\n")
    }

    internal fun extractLinks(body: String): List<String> {
        if (body.isBlank()) return emptyList()
        val links = LINK_REGEX.findAll(body).map { it.value.trim() }.filter { it.length > 8 }.toList()
        if (links.isNotEmpty()) return links
        return try {
            val decoded = String(java.util.Base64.getDecoder().decode(body.filterNot { it.isWhitespace() }.replace('-', '+').replace('_', '/')))
            LINK_REGEX.findAll(decoded).map { it.value.trim() }.filter { it.length > 8 }.toList()
        } catch (_: Exception) {
            emptyList()
        }
    }
}
