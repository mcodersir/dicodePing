package com.v2ray.ang.handler

import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test

class ExitLocationTest {
    @Test fun differentProviderFieldsSelectAnIsoCountryCode() {
        assertEquals(SpeedtestManager.RemoteEndpointInfo("US", "8.8.8.8"),
            SpeedtestManager.parseExitInfo("""{"ip":"8.8.8.8","country":"United States","country_code":"US"}"""))
        assertEquals(SpeedtestManager.RemoteEndpointInfo("AU", "1.1.1.1"),
            SpeedtestManager.parseExitInfo("""{"clientIp":"1.1.1.1","country":"AU"}"""))
    }
    @Test fun fakeDnsPrivateAddressesAndHostnamesCannotBeAnExit() {
        for (ip in listOf("198.18.0.23", "198.19.1.1", "10.1.2.3", "172.18.0.1", "127.0.0.1", "localhost", "::1"))
            assertNull(SpeedtestManager.parseExitInfo("""{"ip":"$ip","country_code":"US"}"""))
    }
}
