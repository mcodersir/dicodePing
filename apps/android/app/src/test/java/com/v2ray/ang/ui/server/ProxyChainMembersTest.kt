package com.v2ray.ang.ui.server

import com.v2ray.ang.R
import com.v2ray.ang.core.CoreConfigContextBuilder
import com.v2ray.ang.dto.ByName
import com.v2ray.ang.dto.entities.ProfileItem
import com.v2ray.ang.enums.EConfigType
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertSame
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class ProxyChainMembersTest {
    private fun dialled(type: EConfigType) = ProfileItem.create(type).apply { server = "203.0.113.7"; serverPort = "443" }

    @Test
    fun aChainIsSavedWhenEachMemberNamesOneProfileAndOneAtMostIsAether() {
        val profiles = mapOf(
            "entry" to dialled(EConfigType.VLESS),
            "warp" to ProfileItem.create(EConfigType.AETHER),
            "exit" to dialled(EConfigType.TROJAN),
        )
        assertNull(proxyChainProblem(listOf("entry", "warp", "exit")) { name, _ -> profiles[name]?.let { ByName.One(it) } ?: ByName.None })
    }

    @Test
    fun aMemberNoProfileHasAnyMoreOrSeveralHaveOrWithoutAServerIsToldByItsName() {
        val found = mapOf<String, ByName<ProfileItem>>(
            "entry" to ByName.One(dialled(EConfigType.VLESS)),
            "twice" to ByName.Several,
            "bare" to ByName.One(ProfileItem.create(EConfigType.TROJAN)),
        )
        fun problem(vararg members: String) = proxyChainProblem(members.toList()) { name, _ -> found[name] ?: ByName.None }
        // The first of the members that cannot be told is named, as the chain names it when it runs.
        assertEquals(ProxyChainProblem.Unresolved("twice", R.string.toast_profile_name_duplicate), problem("entry", "twice", "gone"))
        assertEquals(ProxyChainProblem.Unresolved("gone", R.string.toast_profile_name_not_found), problem("entry", "gone", "twice"))
        assertEquals(ProxyChainProblem.Unresolved("bare", R.string.toast_profile_no_server), problem("entry", "bare"))
        // The same name and message the start gives for the chain.
        for (members in listOf(listOf("entry", "twice", "gone"), listOf("gone", "entry", "twice"), listOf("bare", "gone"))) {
            val atStart = CoreConfigContextBuilder.proxyChainHops(members) { name, _ -> found[name] ?: ByName.None }.second!!
            assertEquals(ProxyChainProblem.Unresolved(atStart.name, atStart.reason.message), problem(*members.toTypedArray()), members.toString())
        }
    }

    @Test
    fun aSecondAetherMemberIsTold() {
        val found = mapOf<String, ByName<ProfileItem>>(
            "warp" to ByName.One(ProfileItem.create(EConfigType.AETHER)),
            "warp 2" to ByName.One(ProfileItem.create(EConfigType.AETHER)),
            "entry" to ByName.One(dialled(EConfigType.VLESS)),
        )
        assertEquals(ProxyChainProblem.SecondAether, proxyChainProblem(listOf("warp", "entry", "warp 2")) { name, _ -> found.getValue(name) })
    }

    @Test
    fun aMemberOnlyAGroupHasIsToldAsAGroupsAsTheStartTellsIt() {
        val profiles = listOf(
            dialled(EConfigType.VLESS).apply { remarks = "entry" },
            dialled(EConfigType.POLICYGROUP).apply { remarks = "group" },
        )
        val find = { name: String, takes: (ProfileItem) -> Boolean -> ByName.find(name, profiles.asSequence().filter(takes)) { it.remarks } }

        assertEquals(ProxyChainProblem.Unresolved("group", R.string.toast_profile_group_not_hop), proxyChainProblem(listOf("entry", "group"), find))
        val atStart = CoreConfigContextBuilder.proxyChainHops(listOf("entry", "group"), find).second!!
        assertEquals(ProxyChainProblem.Unresolved(atStart.name, atStart.reason.message), proxyChainProblem(listOf("entry", "group"), find))
    }

    @Test
    fun removalFollowsThePendingKeyAfterReordering() {
        val pendingKey = "two"
        val members = listOf("Two", "One", "Three")
        val keys = listOf("two", "one", "three")

        val (remainingMembers, remainingKeys) = withoutProxyChainMember(members, keys, pendingKey)

        assertEquals(listOf("One", "Three"), remainingMembers)
        assertEquals(listOf("one", "three"), remainingKeys)
        assertEquals(listOf("Two", "One", "Three"), members)
        assertEquals(listOf("two", "one", "three"), keys)
    }

    @Test
    fun duplicateNamesDoNotChangeWhichMemberIsRemoved() {
        val (members, keys) = withoutProxyChainMember(
            listOf("Same", "Same", "Other"),
            listOf("first", "second", "third"),
            "second",
        )

        assertEquals(listOf("Same", "Other"), members)
        assertEquals(listOf("first", "third"), keys)
    }

    @Test
    fun missingMemberLeavesBothListsUnchanged() {
        val members = listOf("One", "Three")
        val keys = listOf("one", "three")

        val (remainingMembers, remainingKeys) = withoutProxyChainMember(members, keys, "two")

        assertSame(members, remainingMembers)
        assertSame(keys, remainingKeys)
    }

    @Test
    fun emptyChainRemainsEmpty() {
        assertEquals(
            emptyList<String>() to emptyList<String>(),
            withoutProxyChainMember(emptyList(), emptyList(), "missing"),
        )
    }

    @Test
    fun blankMemberIsRemovedWithItsOwnKey() {
        assertEquals(
            listOf("One") to listOf("one"),
            withoutProxyChainMember(listOf("One", ""), listOf("one", "blank"), "blank"),
        )
    }

    @Test
    fun anAetherMemberCanStandAnywhereButOnlyOnce() {
        assertFalse(hasSecondAetherMember(listOf(EConfigType.AETHER, EConfigType.VLESS)))
        assertFalse(hasSecondAetherMember(listOf(EConfigType.VLESS, EConfigType.AETHER)))
        assertFalse(hasSecondAetherMember(listOf(EConfigType.VLESS, EConfigType.AETHER, EConfigType.TROJAN)))
        assertFalse(hasSecondAetherMember(listOf(EConfigType.VLESS, EConfigType.TROJAN)))
        assertFalse(hasSecondAetherMember(listOf(null, EConfigType.VLESS)))
        assertTrue(hasSecondAetherMember(listOf(EConfigType.AETHER, EConfigType.AETHER)))
        assertTrue(hasSecondAetherMember(listOf(EConfigType.AETHER, EConfigType.VLESS, EConfigType.AETHER)))
    }
}
