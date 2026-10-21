package com.v2ray.ang.handler

import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

/** Unit tests for SettingsManager.usesXrayTun: Xray-core's own TUN inbound carries the traffic of the VPN mode only. */
class XrayTunModeTest {

    @Test
    fun theVpnModeUsesXrayTunUnlessHevTunIsOn() {
        assertTrue(SettingsManager.usesXrayTun(vpnMode = true, rootMode = false, hevTun = false))
        assertFalse(SettingsManager.usesXrayTun(vpnMode = true, rootMode = false, hevTun = true))
    }

    @Test
    fun theRootModeNeverUsesXrayTunSinceItRunsItsOwnHevTun() {
        assertFalse(SettingsManager.usesXrayTun(vpnMode = true, rootMode = true, hevTun = false), "root mode with the VPN mode selected")
        assertFalse(SettingsManager.usesXrayTun(vpnMode = true, rootMode = true, hevTun = true), "root mode with HEV TUN on")
        assertFalse(SettingsManager.usesXrayTun(vpnMode = false, rootMode = true, hevTun = false), "root mode with the proxy-only mode selected")
    }

    @Test
    fun theProxyOnlyModeNeverUsesXrayTun() {
        assertFalse(SettingsManager.usesXrayTun(vpnMode = false, rootMode = false, hevTun = false))
        assertFalse(SettingsManager.usesXrayTun(vpnMode = false, rootMode = false, hevTun = true))
    }
}
