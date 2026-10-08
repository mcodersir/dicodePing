package com.v2ray.ang.handler

import com.v2ray.ang.AppConfig
import java.util.Base64
import org.junit.Assert.assertEquals
import org.junit.Test

class PrimarySubscriptionSourcesTest {
    @Test fun existingInstallationAndDeletedSourceAreNeverReprovisioned() {
        assertEquals(true, PrimarySubscriptionSources.shouldProvisionPrimary(false, false, false))
        assertEquals(false, PrimarySubscriptionSources.shouldProvisionPrimary(false, false, true))
        assertEquals(false, PrimarySubscriptionSources.shouldProvisionPrimary(false, true, false))
        assertEquals(false, PrimarySubscriptionSources.shouldProvisionPrimary(true, false, false))
    }
    @Test fun parsedIdentityDropsNamesButPreservesDistinctCredentials() {
        val first = com.v2ray.ang.dto.entities.ProfileItem.create(com.v2ray.ang.enums.EConfigType.VLESS).apply {
            server = "example.org"; serverPort = "443"; password = "secret"; remarks = "Sponsor A"
        }
        val renamed = first.copy(remarks = "Sponsor B", addedTime = first.addedTime + 1, subscriptionId = "second")
        assertEquals(1, listOf(first, renamed).distinctBy { it.duplicateIdentity() }.size)
        assertEquals(2, listOf(first, renamed.copy(password = "other")).distinctBy { it.duplicateIdentity() }.size)
    }
    @Test fun exactlyTheRequestedSourcesAreConfiguredInOrder() {
        assertEquals(listOf(AppConfig.DICODE_PRIMARY_SUBSCRIPTION_URL, AppConfig.DICODE_SECONDARY_SUBSCRIPTION_URL),
            PrimarySubscriptionSources.DEFAULT_SOURCES.map { it.url })
    }
    @Test fun supportsPlainAndUrlSafeBase64WithoutPadding() {
        val text = "vless://id@example.com:443?security=tls#one\ntrojan://pass@example.org:443#two"
        val expected = text.split("\n")
        assertEquals(expected, PrimarySubscriptionSources.extractLinks(text))
        val encoded = Base64.getUrlEncoder().withoutPadding().encodeToString(text.toByteArray())
        assertEquals(expected, PrimarySubscriptionSources.extractLinks(encoded))
    }
    @Test fun rejectsEmptyAndHtmlResponses() {
        assertEquals(emptyList<String>(), PrimarySubscriptionSources.extractLinks(""))
        assertEquals(emptyList<String>(), PrimarySubscriptionSources.extractLinks("<html>upstream unavailable</html>"))
    }
}
