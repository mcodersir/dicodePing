package com.v2ray.ang.handler

import com.v2ray.ang.AppConfig
import com.v2ray.ang.dto.UrlContentRequest
import com.v2ray.ang.util.HttpUtil

/**
 * Aggregates the free-config sources behind the DicodeSpo subscription.
 * Sources are fetched in priority order; plain links are taken as-is and
 * base64 bodies are decoded. Results are deduplicated and capped.
 */
object SpoSourcesAggregator {

    data class SpoSource(val name: String, val url: String)

    val DEFAULT_SOURCES = listOf(
        SpoSource("Patterniha Free-Configs", "https://raw.githubusercontent.com/patterniha/Free-Configs/main/configs.txt"),
        SpoSource("0xRadikal Top100", "https://raw.githubusercontent.com/0xRadikal/Free-v2ray-Configs/refs/heads/main/top100.txt"),
        SpoSource("roosterkid openproxylist", "https://raw.githubusercontent.com/roosterkid/openproxylist/main/V2RAY_RAW.txt"),
        SpoSource("ermaozi get_subscribe", "https://raw.githubusercontent.com/ermaozi/get_subscribe/main/subscribe/v2ray.txt"),
        SpoSource("MatinGhanbari v2ray-configs", "https://raw.githubusercontent.com/MatinGhanbari/v2ray-configs/main/subscriptions/v2ray/all_sub.txt"),
        SpoSource("barry-far v2ray-config", "https://raw.githubusercontent.com/barry-far/v2ray-config/main/All_Configs_Sub.txt"),
        SpoSource("SoliSpirit v2ray-configs", "https://raw.githubusercontent.com/SoliSpirit/v2ray-configs/main/all_configs.txt"),
        SpoSource("Pawdroid Free-servers", "https://raw.githubusercontent.com/Pawdroid/Free-servers/main/sub"),
        SpoSource("peasoft NoMoreWalls", "https://raw.githubusercontent.com/peasoft/NoMoreWalls/master/list.txt"),
        SpoSource("Epodonios v2ray-configs", "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/All_Configs_Sub.txt"),
    )

    private val LINK_REGEX = Regex("(?:vmess|vless|trojan|ss|ssr|hysteria2?|hy2|tuic)://[^\\s\"'<>\\\\]+")

    fun aggregate(maxConfigs: Int = 500): String {
        val collected = LinkedHashSet<String>()
        for (source in DEFAULT_SOURCES) {
            if (collected.size >= maxConfigs) break
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
                    if (collected.size >= maxConfigs) break
                    collected.add(link)
                }
            } catch (_: Exception) {
                // Best effort: a failed source is skipped.
            }
        }
        return collected.joinToString("\n")
    }

    private fun extractLinks(body: String): List<String> {
        if (body.isBlank()) return emptyList()
        val links = LINK_REGEX.findAll(body).map { it.value.trim() }.filter { it.length > 8 }.toList()
        if (links.isNotEmpty()) return links
        return try {
            val decoded = String(android.util.Base64.decode(body.trim(), android.util.Base64.DEFAULT))
            LINK_REGEX.findAll(decoded).map { it.value.trim() }.filter { it.length > 8 }.toList()
        } catch (_: Exception) {
            emptyList()
        }
    }
}
