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

    fun getRemoteIPInfo(): RemoteEndpointInfo? {
        val url = MmkvManager.decodeSettingsString(AppConfig.PREF_IP_API_URL)
            .takeIf { !it.isNullOrBlank() } ?: AppConfig.IP_API_URL

        val proxyUsername = SettingsManager.getSocksUsername()
        val proxyPassword = SettingsManager.getSocksPassword()
        val httpPort = SettingsManager.getHttpPort()
        if (httpPort == 0) return null
        val content = HttpUtil.getUrlContent(
            UrlContentRequest(
                url = url,
                timeout = 5000,
                httpPort = httpPort,
                proxyUsername = proxyUsername,
                proxyPassword = proxyPassword
            )
        ) ?: return null
        val ipInfo = JsonUtil.fromJsonSafe(content, IPAPIInfo::class.java) ?: return null

        val ip = listOf(
            ipInfo.ip,
            ipInfo.clientIp,
            ipInfo.ip_addr,
            ipInfo.query
        ).firstOrNull { !it.isNullOrBlank() }

        val country = listOf(
            ipInfo.country_code,
            ipInfo.country,
            ipInfo.countryCode,
            ipInfo.location?.country_code
        ).firstOrNull { !it.isNullOrBlank() }

        return RemoteEndpointInfo(
            country = country,
            ipAddress = ip,
        )
    }

    /** Queries the proxy exit itself, never the server hostname or the direct connection. */
    fun getProxyLocationInfo(port: Int): RemoteEndpointInfo? {
        if (port !in 1..65535) return null
        val url = MmkvManager.decodeSettingsString(AppConfig.PREF_IP_API_URL).takeIf { !it.isNullOrBlank() } ?: AppConfig.IP_API_URL
        val client = okhttp3.OkHttpClient.Builder()
            .proxy(java.net.Proxy(java.net.Proxy.Type.SOCKS, InetSocketAddress("127.0.0.1", port)))
            .callTimeout(8, java.util.concurrent.TimeUnit.SECONDS).build()
        try {
            return client.newCall(okhttp3.Request.Builder().url(url).build()).execute().use { response ->
                if (!response.isSuccessful) return@use null
                val info = JsonUtil.fromJsonSafe(response.body.string(), com.v2ray.ang.dto.IPAPIInfo::class.java) ?: return@use null
                val ip = listOf(info.ip, info.clientIp, info.ip_addr, info.query).firstOrNull { !it.isNullOrBlank() } ?: return@use null
                val country = listOf(info.country_code, info.countryCode, info.location?.country_code, info.country).firstOrNull { !it.isNullOrBlank() }
                RemoteEndpointInfo(country, ip)
            }
        } finally { client.dispatcher.cancelAll(); client.connectionPool.evictAll(); client.dispatcher.executorService.shutdown() }
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
