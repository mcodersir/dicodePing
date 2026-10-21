package com.v2ray.ang.handler

import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

/** Unit tests for SettingsManager.keepsLocalProxy and appendsHttpProxy: when the core keeps its local proxy, and when the VPN hands it to apps. */
class LocalProxyTest {

    @Test
    fun hevTunInTheVpnModeKeepsTheLocalProxyWhateverIsSet() {
        assertTrue(SettingsManager.keepsLocalProxy(vpnMode = true, hevTun = true, rootMode = false, lanSharing = false, localProxySet = false))
    }

    @Test
    fun xrayTunInTheVpnModeKeepsTheLocalProxyOnlyAsSet() {
        assertTrue(SettingsManager.keepsLocalProxy(vpnMode = true, hevTun = false, rootMode = false, lanSharing = false, localProxySet = true))
        assertFalse(SettingsManager.keepsLocalProxy(vpnMode = true, hevTun = false, rootMode = false, lanSharing = false, localProxySet = false))
    }

    @Test
    fun theRootModeAndItsLanSharingKeepTheLocalProxyWhateverIsSet() {
        assertTrue(SettingsManager.keepsLocalProxy(vpnMode = true, hevTun = false, rootMode = true, lanSharing = false, localProxySet = false), "root mode")
        assertTrue(SettingsManager.keepsLocalProxy(vpnMode = true, hevTun = false, rootMode = false, lanSharing = true, localProxySet = false), "LAN sharing in the VPN mode")
        assertTrue(SettingsManager.keepsLocalProxy(vpnMode = false, hevTun = false, rootMode = true, lanSharing = false, localProxySet = false), "root mode with the proxy-only mode selected")
    }

    @Test
    fun theProxyOnlyModeKeepsTheLocalProxyOnlyAsSet() {
        assertFalse(SettingsManager.keepsLocalProxy(vpnMode = false, hevTun = true, rootMode = false, lanSharing = false, localProxySet = false))
        assertTrue(SettingsManager.keepsLocalProxy(vpnMode = false, hevTun = false, rootMode = false, lanSharing = false, localProxySet = true))
    }

    @Test
    fun theHttpProxyIsAppendedOnlyWhileTheLocalProxyIsKept() {
        assertTrue(SettingsManager.appendsHttpProxy(appendSet = true, localProxyKept = true))
        assertFalse(SettingsManager.appendsHttpProxy(appendSet = true, localProxyKept = false), "the local proxy is gone")
        assertFalse(SettingsManager.appendsHttpProxy(appendSet = false, localProxyKept = true))
    }
}
