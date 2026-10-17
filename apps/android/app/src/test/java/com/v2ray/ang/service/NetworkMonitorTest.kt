package com.v2ray.ang.service

import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test
import org.mockito.kotlin.argumentCaptor
import org.mockito.kotlin.mock
import org.mockito.kotlin.verify

class NetworkMonitorTest {
    @Test
    fun lossOrCapabilitiesOfOldNetworkCannotClearTheNewUplink() {
        val logLevel = com.v2ray.ang.util.LogUtil::class.java.getDeclaredField("cachedMinPriority").apply { isAccessible = true }
        val previousLogLevel = logLevel.getInt(null)
        logLevel.setInt(null, Int.MAX_VALUE)
        try {
        val connectivity = mock<ConnectivityManager>()
        val request = mock<NetworkRequest>()
        val seen = mutableListOf<Network?>()
        val monitor = NetworkMonitor(connectivity, { seen += it?.firstOrNull() }, {}, { request })
        monitor.register()
        val callbacks = argumentCaptor<ConnectivityManager.NetworkCallback>()
        verify(connectivity).requestNetwork(org.mockito.kotlin.eq(request), callbacks.capture())
        val old = mock<Network>()
        val current = mock<Network>()
        callbacks.firstValue.onAvailable(old)
        callbacks.firstValue.onAvailable(current)
        callbacks.firstValue.onLost(old)
        callbacks.firstValue.onCapabilitiesChanged(old, mock<NetworkCapabilities>())
        assertEquals(listOf(old, current), seen)
        callbacks.firstValue.onLost(current)
        assertEquals(listOf(old, current, null), seen)
        monitor.unregister()
        } finally { logLevel.setInt(null, previousLogLevel) }
    }
}
