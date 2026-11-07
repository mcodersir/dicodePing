package com.v2ray.ang.handler

import com.v2ray.ang.AppConfig
import com.v2ray.ang.dto.UrlContentRequest

/**
 * Fetches only Dicode Config Checker. Other feeds are independent subscriptions.
 * Plain links and base64 bodies are decoded and deduplicated within this feed.
 */
object PrimarySubscriptionSources {

    internal fun shouldProvisionPrimary(hasPrimary: Boolean, deleted: Boolean, existingSettings: Boolean): Boolean =
        !hasPrimary && !deleted && !existingSettings

    data class Source(val name: String, val url: String)

    val DEFAULT_SOURCES = listOf(
        Source("Dicode Config Checker", AppConfig.DICODE_PRIMARY_SUBSCRIPTION_URL),

    )

    private val LINK_REGEX = Regex("(?:vmess|vless|trojan|ss|ssr|hysteria2?|hy2|tuic)://[^\\s\"'<>\\\\]+")

    fun aggregate(): String {
        val executor = java.util.concurrent.Executors.newFixedThreadPool(2)
        return try {
            val requests = DEFAULT_SOURCES.map { source -> executor.submit<List<String>> { fetch(source) } }
            val collected = LinkedHashMap<String, String>()
            // Fetch concurrently, merge in the requested priority order.
            requests.forEach { request -> request.get().forEach { link -> collected.putIfAbsent(link.substringBefore("#"), link) } }
            collected.values.joinToString("\n")
        } finally { executor.shutdownNow() }
    }

    private fun fetch(source: Source): List<String> {
        return try {
            val response = SubscriptionDownload.fetch(
                UrlContentRequest(
                    url = source.url, timeout = 30000,
                    httpPort = SettingsManager.getHttpPort(),
                    proxyUsername = SettingsManager.getSocksUsername(),
                    proxyPassword = SettingsManager.getSocksPassword()
                ),
                proxyRunning = SubscriptionDownload.isProxyListening(SettingsManager.getHttpPort()),
                directFirst = true,
                accept = { extractLinks(it).isNotEmpty() }
            )
            extractLinks(response.content)
        } catch (interrupted: InterruptedException) {
            Thread.currentThread().interrupt()
            throw interrupted
        } catch (_: java.io.IOException) {
            emptyList()
        }
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
