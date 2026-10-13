package com.v2ray.ang.ui.main

import com.v2ray.ang.AppResources
import com.v2ray.ang.dto.entities.ProfileItem
import com.v2ray.ang.enums.AetherProtocol
import com.v2ray.ang.enums.EConfigType
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test

class MainServerRowModelsTest {

    private fun aether(block: ProfileItem.() -> Unit = {}) = ProfileItem.create(EConfigType.AETHER).apply(block)

    /** The names the editor's protocol list gives, as the main screen reads them. */
    private val labels = aetherProtocolLabels(AppResources.stringArray("aether_protocol_entries"), AppResources.stringArray("aether_protocol_values"))

    private fun description(profile: ProfileItem) = serverProtocolDescription(profile, labels)

    @Test
    fun anAetherRowNamesTheTunnelFromTheOutsideIn() {
        assertEquals("AETHER / WireGuard", description(aether()))
        assertEquals("AETHER / WireGuard → PSIPHON", description(aether { aetherProtocol = "wg"; aetherPsiphon = "chain" }))
        assertEquals("AETHER / TOR → MASQUE", description(aether { aetherProtocol = "masque"; aetherTor = "reverse" }))
        assertEquals("AETHER / MASQUE-in-MASQUE → TOR", description(aether { aetherProtocol = "mim"; aetherTor = "chain" }))
        // A carrier alone is the whole tunnel; no WARP protocol is named for it.
        assertEquals("AETHER / PSIPHON", description(aether { aetherProtocol = "wg"; aetherPsiphon = "only" }))
        assertEquals("AETHER / TOR", description(aether { aetherTor = "only" }))
        // A command written by hand is read the same way.
        assertEquals("AETHER / WireGuard over MASQUE → TOR", description(aether { aetherCommand = "aether --gool --tor" }))
        assertEquals("AETHER / WARP-in-WARP → TOR", description(aether { aetherCommand = "aether --gool-classic --tor" }))
        assertEquals("AETHER / WARP-in-WARP", description(aether { aetherProtocol = "gool" }))
        assertEquals("AETHER / WireGuard over MASQUE", description(aether { aetherProtocol = "wg-over-masque" }))
    }

    @Test
    fun everyWarpProtocolHasTheNameTheEditorGivesIt() {
        val entries = AppResources.stringArray("aether_protocol_entries")
        val values = AppResources.stringArray("aether_protocol_values")
        assertEquals(entries.size, values.size)
        for (protocol in AetherProtocol.entries) {
            assertEquals(entries[values.indexOf(protocol.type)], labels(protocol), protocol.name)
        }
        // A protocol the list lacks keeps its own name, as when the names cannot be read.
        assertEquals("WG_OVER_MASQUE", aetherProtocolLabels(emptyList(), emptyList())(AetherProtocol.WG_OVER_MASQUE))
    }
}
