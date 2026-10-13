package com.v2ray.ang.core

import com.v2ray.ang.dto.entities.ProfileItem
import com.v2ray.ang.enums.EConfigType
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test

class FoxProfileTest {
    @Test fun managedSocksReferencesAnAccountWithoutPuttingItsTokenInTheProfile() {
        val id = "1234567890abcdef1234567890abcdef"
        val node = ProfileItem(configType = EConfigType.SOCKS, server = "127.0.0.1", serverPort = "7854", foxAccountId = id, foxCountry = "de")
        assertEquals(FoxProfile(id, "DE"), FoxAccounts.profile(node))
        assertEquals("socks5://127.0.0.1:7854#Firefox-VPN", FoxAccounts.SHARE_URI)
        assertNull(node.password)
        assertThrows(FoxError::class.java) { FoxAccounts.profile(node.copy(server = "remote.example")) }
        assertThrows(FoxError::class.java) { FoxAccounts.profile(node.copy(serverPort = "1080")) }
        assertNull(FoxAccounts.profile(node.copy(foxAccountId = null)))
    }
}
