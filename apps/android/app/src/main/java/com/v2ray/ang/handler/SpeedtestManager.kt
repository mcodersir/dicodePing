package com.v2ray.ang.handler

import com.v2ray.ang.AppConfig
import com.v2ray.ang.dto.IPAPIInfo
import com.v2ray.ang.dto.UrlContentRequest
import com.v2ray.ang.util.HttpUtil
import com.v2ray.ang.util.JsonUtil
import com.v2ray.ang.util.LogUtil
import java.io.IOException
import java.net.InetSocketAddress
import java.net.InetAddress
import java.net.Socket
import java.net.UnknownHostException

object SpeedtestManager {

    data class RemoteEndpointInfo(
        val country: String?,
        val ipAddress: String?,
    )

    /**
     * Measures the time taken to establish a TCP connection to a given URL and port.
     *
     * @param url The URL to connect to.
     * @param port The port to connect to.
     * @return The connection time in milliseconds, or -1 if the connection failed.
     */
    fun socketConnectTime(url: String, port: Int, timeoutMs: Int = 1500): Long {
        var socket: Socket? = null
        val start = System.currentTimeMillis()

        try {
            socket = Socket()
            socket.connect(InetSocketAddress(url, port), timeoutMs)

            return System.currentTimeMillis() - start
        } catch (e: UnknownHostException) {
            LogUtil.e(AppConfig.TAG, "Unknown host: $url", e)
        } catch (e: IOException) {
            LogUtil.e(AppConfig.TAG, "socketConnectTime IOException: ${e.message}")
        } catch (e: Exception) {
            LogUtil.e(AppConfig.TAG, "Failed to establish socket connection to $url:$port", e)
        } finally {
            socket?.let { s ->
                try {
                    if (!s.isClosed) {
                        s.close()
                    }
                } catch (closeEx: IOException) {
                }
            }
        }
        return -1
    }

    fun getRemoteIPInfo(): RemoteEndpointInfo? = getProxyLocationInfo(SettingsManager.getSocksPort(), true)

    /** Exit lookup is independent of latency. No request can fall back to a direct connection. */
    fun getProxyLocationInfo(port: Int, active: Boolean = false): RemoteEndpointInfo? {
        if (port !in 1..65535) return null
        val preferred = MmkvManager.decodeSettingsString(AppConfig.PREF_IP_API_URL).takeIf { !it.isNullOrBlank() }
        val urls = listOfNotNull(preferred, AppConfig.IP_API_URL, "https://speed.cloudflare.com/meta", "https://api.ipapi.is").distinct()
        val username = if (active) SettingsManager.getSocksUsername() else null
        val password = if (active) SettingsManager.getSocksPassword() else null
        val authenticated = !username.isNullOrBlank() && !password.isNullOrBlank()
        val client = okhttp3.OkHttpClient.Builder()
            .proxy(java.net.Proxy(if (authenticated) java.net.Proxy.Type.HTTP else java.net.Proxy.Type.SOCKS,
                InetSocketAddress("127.0.0.1", if (authenticated) SettingsManager.getHttpPort() else port)))
            .proxyAuthenticator { _, response ->
                if (!authenticated || response.request.header("Proxy-Authorization") != null) null
                else response.request.newBuilder().header("Proxy-Authorization", okhttp3.Credentials.basic(username!!, password!!)).build()
            }
            .followRedirects(false).followSslRedirects(false)
            .callTimeout(3, java.util.concurrent.TimeUnit.SECONDS).build()
        try {
            for (url in urls) {
                try {
                    val result = client.newCall(okhttp3.Request.Builder().url(url).build()).execute().use { response ->
                        if (!response.isSuccessful) null else parseExitInfo(response.peekBody(65536).string())
                    }
                    if (result != null) return result
                } catch (_: Exception) { /* Another provider can still describe this exit. */ }
            }
            return null
        } finally { client.dispatcher.cancelAll(); client.connectionPool.evictAll(); client.dispatcher.executorService.shutdown() }
    }

    internal fun parseExitInfo(content: String): RemoteEndpointInfo? {
        val info = JsonUtil.fromJsonSafe(content, IPAPIInfo::class.java) ?: return null
        val ip = listOf(info.ip, info.clientIp, info.ip_addr, info.query).firstOrNull { !it.isNullOrBlank() } ?: return null
        // Only numeric public exit addresses, never a hostname or the TUN fake-DNS range.
        if (!ip.matches(Regex("[0-9a-fA-F:.]+"))) return null
        val address = runCatching { InetAddress.getByName(ip) }.getOrNull() ?: return null
        if (address.isAnyLocalAddress || address.isLoopbackAddress || address.isSiteLocalAddress || address.isLinkLocalAddress ||
            ip.startsWith("198.18.") || ip.startsWith("198.19.")) return null
        val country = listOf(info.country_code, info.countryCode, info.location?.country_code, info.country)
            .firstOrNull { it?.matches(Regex("[a-zA-Z]{2}")) == true } ?: return null
        return RemoteEndpointInfo(country.uppercase(java.util.Locale.ROOT), ip)
    }

    /**
     * Beta location lookup for a configuration endpoint. This intentionally uses
     * the endpoint address, rather than the currently selected VPN route, so a
     * batch test can never overwrite or be confused with a saved real ping.
     */
    fun getServerLocationInfo(host: String?): RemoteEndpointInfo? {
        if (host.isNullOrBlank()) return null
        val ip = runCatching { InetAddress.getByName(host).hostAddress }.getOrNull() ?: return null
        val baseUrl = MmkvManager.decodeSettingsString(AppConfig.PREF_IP_API_URL)
            .takeIf { !it.isNullOrBlank() } ?: AppConfig.IP_API_URL
        val content = HttpUtil.getUrlContent(
            UrlContentRequest(url = "${baseUrl.trimEnd('/')}/$ip", timeout = 5000)
        ) ?: return RemoteEndpointInfo(country = null, ipAddress = ip)
        val info = JsonUtil.fromJsonSafe(content, IPAPIInfo::class.java)
        val country = info?.let {
            listOf(it.country_code, it.countryCode, it.location?.country_code, it.country)
                .firstOrNull { value -> !value.isNullOrBlank() }
        }
        return RemoteEndpointInfo(country = country, ipAddress = ip)
    }
}
