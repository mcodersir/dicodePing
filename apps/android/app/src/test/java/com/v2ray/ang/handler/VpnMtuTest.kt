package com.v2ray.ang.handler

import com.v2ray.ang.AppConfig
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test

/** Unit tests for SettingsManager.vpnMtu: the VPN MTU setting, which VpnService.Builder.setMtu takes only above 0. */
class VpnMtuTest {

    @Test
    fun aNumberAboveZeroIsTheMtu() {
        assertEquals(1400, SettingsManager.vpnMtu("1400"))
        assertEquals(9000, SettingsManager.vpnMtu("9000"))
        assertEquals(1, SettingsManager.vpnMtu("1"))
    }

    @Test
    fun zeroOrLessIsTheDefaultMtu() {
        assertEquals(AppConfig.VPN_MTU, SettingsManager.vpnMtu("0"))
        assertEquals(AppConfig.VPN_MTU, SettingsManager.vpnMtu("-1"))
    }

    @Test
    fun noNumberIsTheDefaultMtu() {
        assertEquals(AppConfig.VPN_MTU, SettingsManager.vpnMtu(null))
        assertEquals(AppConfig.VPN_MTU, SettingsManager.vpnMtu(""))
        assertEquals(AppConfig.VPN_MTU, SettingsManager.vpnMtu(" \n"))
        assertEquals(AppConfig.VPN_MTU, SettingsManager.vpnMtu("mtu"))
        assertEquals(AppConfig.VPN_MTU, SettingsManager.vpnMtu("14 00"))
    }

    @Test
    fun spacesAndLineBreaksAroundTheNumberAreIgnored() {
        // The settings dialog takes several lines, so Enter after the number stores a line break with it.
        assertEquals(1400, SettingsManager.vpnMtu("1400\n"))
        assertEquals(1400, SettingsManager.vpnMtu(" 1400"))
        assertEquals(1400, SettingsManager.vpnMtu("\t1400 \r\n"))
        assertEquals(AppConfig.VPN_MTU, SettingsManager.vpnMtu(" 0\n"))
    }
}
