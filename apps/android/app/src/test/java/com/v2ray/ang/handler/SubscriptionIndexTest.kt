package com.v2ray.ang.handler

import android.util.Log
import com.tencent.mmkv.MMKV
import com.v2ray.ang.dto.entities.ProfileItem
import com.v2ray.ang.dto.entities.ServerAffiliationInfo
import com.v2ray.ang.dto.entities.SubscriptionItem
import com.v2ray.ang.enums.EConfigType
import com.v2ray.ang.util.JsonUtil
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeAll
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.mockito.ArgumentMatchers
import org.mockito.MockMakers
import org.mockito.Mockito
import org.mockito.Mockito.mockStatic
import org.mockito.kotlin.any
import org.mockito.kotlin.clearInvocations
import org.mockito.kotlin.doAnswer
import org.mockito.kotlin.doReturn
import org.mockito.kotlin.eq
import org.mockito.kotlin.inOrder
import org.mockito.kotlin.never
import org.mockito.kotlin.reset
import org.mockito.kotlin.verify
import org.mockito.kotlin.verifyNoInteractions
import org.mockito.kotlin.whenever

class SubscriptionIndexTest {
    private val mainValues = mutableMapOf<String, String>()
    private val subValues = mutableMapOf<String, String>()

    /** The test results stored, by profile, and whether the lock of the test results was held for each write and read of one. */
    private val affiliationValues = mutableMapOf<String, String>()
    private val affiliationWritesLocked = mutableListOf<Boolean>()
    private val affiliationReadsLocked = mutableListOf<Boolean>()

    /** The profiles stored, by guid, and whether the lock of the test results was held as their payloads went. */
    private val profileValues = mutableMapOf<String, String>()
    private val payloadRemovalsUnderResultLock = mutableListOf<Boolean>()

    /** The keys whose writes the storage refuses, as a full device does. */
    private val refusedMainKeys = mutableSetOf<String>()
    private val refusedSubKeys = mutableSetOf<String>()

    /** How many more writes of the main storage it takes; it refuses those after. */
    private var mainWritesLeft = Int.MAX_VALUE

    /** The key of each write of the main storage, in order, with whether the profile index lock was held for it. */
    private val mainWrites = mutableListOf<Pair<String, Boolean>>()

    @BeforeEach
    fun prepareStorage() {
        for ((storage, values, refused) in listOf(Triple(main, mainValues, refusedMainKeys), Triple(subs, subValues, refusedSubKeys))) {
            reset(storage)
            whenever(storage.decodeString(any())).thenAnswer { values[it.getArgument<String>(0)] }
            whenever(storage.encode(any<String>(), any<String>())).thenAnswer {
                val key = it.getArgument<String>(0)
                if (storage === main) {
                    mainWrites += key to Thread.holdsLock(main)
                    if (mainWritesLeft-- <= 0) return@thenAnswer false
                }
                if (key in refused) return@thenAnswer false
                values[key] = it.getArgument(1)
                true
            }
            whenever(storage.allKeys()).thenAnswer { values.keys.toTypedArray() }
            whenever(storage.remove(any())).thenAnswer {
                values.remove(it.getArgument<String>(0))
                null
            }
            doAnswer {
                values.remove(it.getArgument<String>(0))
                null
            }.whenever(storage).removeValueForKey(any())
        }
        reset(profiles, raws, affiliations)
        whenever(affiliations.decodeString(any())).thenAnswer {
            affiliationReadsLocked += Thread.holdsLock(affiliations)
            affiliationValues[it.getArgument<String>(0)]
        }
        whenever(affiliations.allKeys()).thenAnswer { affiliationValues.keys.toTypedArray() }
        whenever(affiliations.encode(any<String>(), any<String>())).thenAnswer {
            affiliationWritesLocked += Thread.holdsLock(affiliations)
            affiliationValues[it.getArgument(0)] = it.getArgument(1)
            true
        }
        whenever(profiles.decodeString(any())).thenAnswer { profileValues[it.getArgument<String>(0)] }
        doAnswer {
            payloadRemovalsUnderResultLock += Thread.holdsLock(affiliations)
            null
        }.whenever(profiles).removeValuesForKeys(any())
    }

    private fun stored(guid: String, subscriptionId: String) {
        profileValues[guid] = JsonUtil.toJson(ProfileItem.create(EConfigType.VLESS).apply { this.subscriptionId = subscriptionId })
    }

    private fun tested(guid: String, delayMillis: Long) {
        affiliationValues[guid] = JsonUtil.toJson(ServerAffiliationInfo(testDelayMillis = delayMillis))
    }

    @Test
    fun poolIsCreatedBeforeResultsAndRenamedWithoutTouchingDefaultSubscription() {
        val primaryId = com.v2ray.ang.AppConfig.DICODE_PRIMARY_SUBSCRIPTION_ID
        val primary = JsonUtil.toJson(SubscriptionItem(remarks = "Default", url = "https://example.com/sub"))
        mainValues["SUB_IDS"] = JsonUtil.toJson(listOf(primaryId))
        subValues[primaryId] = primary
        ServerPoolManager.ensureSubscription()
        ServerPoolManager.ensureSubscription()
        org.junit.Assert.assertTrue(SettingsChangeManager.consumeSetupGroupTab())
        assertEquals(listOf(primaryId, ServerPoolManager.POOL_ID), MmkvManager.decodeSubsList())
        assertEquals(primary, subValues[primaryId])
        assertEquals("سرور های استخر", MmkvManager.decodeSubscription(ServerPoolManager.POOL_ID)?.remarks)
        assertEquals("", MmkvManager.decodeSubscription(ServerPoolManager.POOL_ID)?.url)
        val pool = requireNotNull(MmkvManager.decodeSubscription(ServerPoolManager.POOL_ID))
        MmkvManager.encodeSubscription(ServerPoolManager.POOL_ID, pool.copy(remarks = "استخر کانفیگ", lastUpdated = 1234))
        ServerPoolManager.ensureSubscription()
        assertEquals(1234L, MmkvManager.decodeSubscription(ServerPoolManager.POOL_ID)?.lastUpdated)
        assertEquals(primary, subValues[primaryId])
    }

    @Test
    fun duplicateIdsKeepTheirFirstPositionWithoutWritingStorage() {
        val stored = """["second","first","second","third","first"]"""
        mainValues["SUB_IDS"] = stored

        assertEquals(listOf("second", "first", "third"), MmkvManager.decodeSubsList())
        assertEquals(stored, mainValues["SUB_IDS"])
        verify(main, never()).encode(any<String>(), any<String>())
    }

    @Test
    fun duplicateIndexEntriesProduceOnlyOneSubscriptionRow() {
        mainValues["SUB_IDS"] = """["b","a","b","a"]"""
        subValues["a"] = JsonUtil.toJson(SubscriptionItem(remarks = "Alpha"))
        subValues["b"] = JsonUtil.toJson(SubscriptionItem(remarks = "Beta"))

        val rows = MmkvManager.decodeSubscriptions()

        assertEquals(listOf("b", "a"), rows.map { it.guid })
        assertEquals(listOf("Beta", "Alpha"), rows.map { it.subscription.remarks })
    }

    @Test
    fun repeatedAndBlankNamesDoNotMergeDifferentSubscriptions() {
        mainValues["SUB_IDS"] = """["a","b","c","d"]"""
        listOf("a" to "Same", "b" to "Same", "c" to "", "d" to " ").forEach { (id, name) ->
            subValues[id] = JsonUtil.toJson(SubscriptionItem(remarks = name))
        }

        assertEquals(listOf("a", "b", "c", "d"), MmkvManager.decodeSubscriptions().map { it.guid })
    }

    @Test
    fun decodedIndexRemainsMutableAndCanBeSavedInANewOrder() {
        mainValues["SUB_IDS"] = """["a","b","a"]"""
        val ids = MmkvManager.decodeSubsList()
        ids.remove("a")
        ids.add(0, "c")
        MmkvManager.encodeSubsList(ids)

        assertEquals("""["c","b"]""", mainValues["SUB_IDS"])
        assertEquals(listOf("c", "b"), MmkvManager.decodeSubsList())
    }

    @Test
    fun missingBlankAndEmptyIndexesRemainEmpty() {
        assertEquals(emptyList<String>(), MmkvManager.decodeSubsList())
        listOf("", " ", "[]", "null").forEach { stored ->
            mainValues["SUB_IDS"] = stored
            assertEquals(emptyList<String>(), MmkvManager.decodeSubsList())
        }
    }

    @Test
    fun malformedIndexKeepsTheExistingEmptyFallback() {
        mockStatic(Log::class.java).use {
            mainValues["SUB_IDS"] = "{"
            assertEquals(emptyList<String>(), MmkvManager.decodeSubsList())
        }
    }

    @Test
    fun aNewSubscriptionIsStoredThenListedUnderTheProfileIndexLock() {
        mainValues["SUB_IDS"] = """["a"]"""

        assertEquals("new", MmkvManager.tryEncodeSubscription("new", SubscriptionItem(remarks = "New")))

        assertEquals("New", JsonUtil.fromJson(subValues.getValue("new"), SubscriptionItem::class.java)?.remarks)
        assertEquals(listOf("a", "new"), MmkvManager.decodeSubsList())
        assertEquals(listOf("SUB_IDS" to true), mainWrites)
    }

    @Test
    fun aListedSubscriptionIsWrittenOverWithoutAListWrite() {
        mainValues["SUB_IDS"] = """["a"]"""

        assertEquals("a", MmkvManager.tryEncodeSubscription("a", SubscriptionItem(remarks = "Renamed")))

        assertEquals("Renamed", JsonUtil.fromJson(subValues.getValue("a"), SubscriptionItem::class.java)?.remarks)
        assertTrue(mainWrites.isEmpty())
    }

    @Test
    fun aSubscriptionTheStorageRefusesIsToldAndLeftAsItWas() {
        mainValues["SUB_IDS"] = """["a"]"""
        val stored = JsonUtil.toJson(SubscriptionItem(remarks = "Alpha"))
        subValues["a"] = stored
        refusedSubKeys += "a"

        mockStatic(Log::class.java).use {
            assertNull(MmkvManager.tryEncodeSubscription("a", SubscriptionItem(remarks = "Renamed")))
        }

        assertEquals(stored, subValues["a"])
        assertTrue(mainWrites.isEmpty())
    }

    @Test
    fun aNewSubscriptionTheListRefusesLeavesNothingBehind() {
        mainValues["SUB_IDS"] = """["a"]"""
        refusedMainKeys += "SUB_IDS"

        mockStatic(Log::class.java).use {
            assertNull(MmkvManager.tryEncodeSubscription("new", SubscriptionItem(remarks = "New")))
        }

        assertFalse("new" in subValues)
        assertEquals("""["a"]""", mainValues["SUB_IDS"])
    }

    @Test
    fun aStoredSubscriptionNoListNamesIsPutBackAsItWasStoredWhenTheListRefusesIt() {
        mainValues["SUB_IDS"] = """["a"]"""
        val stored = JsonUtil.toJson(SubscriptionItem(remarks = "Unlisted"))
        subValues["unlisted"] = stored
        refusedMainKeys += "SUB_IDS"

        mockStatic(Log::class.java).use {
            assertNull(MmkvManager.tryEncodeSubscription("unlisted", SubscriptionItem(remarks = "Renamed")))
        }

        assertEquals(stored, subValues["unlisted"])
    }

    @Test
    fun aSubscriptionGoesOutOfItsListThenWithItsProfilesUnderTheProfileIndexLock() {
        mainValues["SUB_IDS"] = """["a","b"]"""
        mainValues["SUB_SERVERS_a"] = """["p1","p2"]"""
        mainValues["SELECTED_SERVER"] = "p2"
        subValues["a"] = JsonUtil.toJson(SubscriptionItem(remarks = "Alpha"))
        subValues["b"] = JsonUtil.toJson(SubscriptionItem(remarks = "Beta"))

        assertTrue(MmkvManager.tryRemoveSubscription("a"))

        assertEquals(listOf("b"), MmkvManager.decodeSubsList())
        assertEquals("[]", mainValues["SUB_SERVERS_a"])
        // The profile the app ran on was one of them.
        assertFalse("SELECTED_SERVER" in mainValues)
        assertFalse("a" in subValues)
        assertTrue("b" in subValues)
        // Their payloads, raw configurations among them, go once both lists are written.
        verify(profiles).removeValuesForKeys(arrayOf("p1", "p2"))
        verify(raws).removeValuesForKeys(arrayOf("p1", "p2"))
        verify(affiliations).removeValuesForKeys(arrayOf("p1", "p2"))
        assertEquals(listOf("SUB_IDS" to true, "SUB_SERVERS_a" to true), mainWrites)
    }

    @Test
    fun aSubscriptionListTheStorageRefusesLeavesTheSubscriptionAsItWas() {
        val ids = """["a","b"]"""
        mainValues["SUB_IDS"] = ids
        mainValues["SUB_SERVERS_a"] = """["p1"]"""
        mainValues["SELECTED_SERVER"] = "p1"
        subValues["a"] = JsonUtil.toJson(SubscriptionItem(remarks = "Alpha"))
        refusedMainKeys += "SUB_IDS"

        mockStatic(Log::class.java).use {
            assertFalse(MmkvManager.tryRemoveSubscription("a"))
        }

        assertEquals(ids, mainValues["SUB_IDS"])
        assertEquals("""["p1"]""", mainValues["SUB_SERVERS_a"])
        assertEquals("p1", mainValues["SELECTED_SERVER"])
        assertTrue("a" in subValues)
        verifyNoInteractions(profiles, raws, affiliations)
    }

    @Test
    fun aListOfProfilesTheStorageRefusesPutsTheSubscriptionListBackAsItWasStored() {
        // Stored with a repeat, which goes back as it was stored.
        val ids = """["b","a","b"]"""
        mainValues["SUB_IDS"] = ids
        mainValues["SUB_SERVERS_a"] = """["p1"]"""
        subValues["a"] = JsonUtil.toJson(SubscriptionItem(remarks = "Alpha"))
        refusedMainKeys += "SUB_SERVERS_a"

        mockStatic(Log::class.java).use {
            assertFalse(MmkvManager.tryRemoveSubscription("a"))
        }

        assertEquals(ids, mainValues["SUB_IDS"])
        assertEquals("""["p1"]""", mainValues["SUB_SERVERS_a"])
        assertTrue("a" in subValues)
        verifyNoInteractions(profiles, raws, affiliations)
    }

    @Test
    fun aSubscriptionTheStorageRefusesBackInItsListStaysOutOfItWithItsProfiles() {
        mainValues["SUB_IDS"] = """["a","b"]"""
        mainValues["SUB_SERVERS_a"] = """["p1"]"""
        subValues["a"] = JsonUtil.toJson(SubscriptionItem(remarks = "Alpha"))
        // The first write is taken, the list of its profiles and the list put back are refused.
        mainWritesLeft = 1

        mockStatic(Log::class.java).use {
            assertFalse(MmkvManager.tryRemoveSubscription("a"))
        }

        assertEquals(listOf("b"), MmkvManager.decodeSubsList())
        assertEquals("""["p1"]""", mainValues["SUB_SERVERS_a"])
        assertTrue("a" in subValues)
        verifyNoInteractions(profiles, raws, affiliations)
        assertEquals(listOf("SUB_IDS", "SUB_SERVERS_a", "SUB_IDS"), mainWrites.map { it.first })
    }

    @Test
    fun aDamagedListOfProfilesIsWrittenEmptyToo() {
        mainValues["SUB_IDS"] = """["a","b"]"""
        mainValues["SUB_SERVERS_a"] = "{"
        subValues["a"] = JsonUtil.toJson(SubscriptionItem(remarks = "Alpha"))

        mockStatic(Log::class.java).use {
            assertTrue(MmkvManager.tryRemoveSubscription("a"))
        }

        assertEquals("[]", mainValues["SUB_SERVERS_a"])
        assertEquals(listOf("SUB_IDS" to true, "SUB_SERVERS_a" to true), mainWrites)
        assertFalse("a" in subValues)
        verifyNoInteractions(profiles, raws, affiliations)
    }

    @Test
    fun theSubscriptionListIsRebuiltFromThePayloadsUnderTheProfileIndexLock() {
        subValues["a"] = JsonUtil.toJson(SubscriptionItem(remarks = "Alpha"))

        assertEquals(listOf("a"), MmkvManager.decodeSubscriptions().map { it.guid })

        assertEquals(listOf("SUB_IDS" to true), mainWrites)
    }

    @Test
    fun aSubscriptionIsMovedByTheKeysInTheListAsStoredUnderTheProfileIndexLock() {
        // "d" was listed by another writer after the screen read the list.
        mainValues["SUB_IDS"] = """["a","b","c","d"]"""

        assertTrue(MmkvManager.tryMoveSubscription("c", "a"))

        assertEquals(listOf("c", "a", "b", "d"), MmkvManager.decodeSubsList())
        assertEquals(listOf("SUB_IDS" to true), mainWrites)
    }

    @Test
    fun aMoveTheStorageRefusesIsToldAndLeavesTheListAsItWas() {
        val ids = """["a","b","c"]"""
        mainValues["SUB_IDS"] = ids
        refusedMainKeys += "SUB_IDS"

        mockStatic(Log::class.java).use {
            assertFalse(MmkvManager.tryMoveSubscription("c", "a"))
        }

        assertEquals(ids, mainValues["SUB_IDS"])
    }

    @Test
    fun aMoveOfASubscriptionNoLongerListedWritesNothing() {
        mainValues["SUB_IDS"] = """["a","b"]"""

        assertTrue(MmkvManager.tryMoveSubscription("gone", "a"))
        assertTrue(MmkvManager.tryMoveSubscription("a", "gone"))

        assertTrue(mainWrites.isEmpty())
    }

    @Test
    fun aSwitchTurnsTheSubscriptionAsStoredOnOrOffWithoutTouchingTheList() {
        mainValues["SUB_IDS"] = """["a"]"""
        // An update wrote its time after the list read the subscription.
        subValues["a"] = JsonUtil.toJson(SubscriptionItem(remarks = "Alpha", lastUpdated = 42L))

        assertTrue(MmkvManager.trySetSubscriptionEnabled("a", false))

        val stored = JsonUtil.fromJson(subValues.getValue("a"), SubscriptionItem::class.java)
        assertEquals(false, stored?.enabled)
        assertEquals(42L, stored?.lastUpdated)
        assertTrue(mainWrites.isEmpty())
    }

    @Test
    fun aSwitchOfASubscriptionRemovedMeanwhileOrAlreadySoWritesNothing() {
        mainValues["SUB_IDS"] = """["a"]"""
        val stored = JsonUtil.toJson(SubscriptionItem(remarks = "Alpha"))
        subValues["a"] = stored

        assertTrue(MmkvManager.trySetSubscriptionEnabled("gone", false))
        assertTrue(MmkvManager.trySetSubscriptionEnabled("a", true))

        verify(subs, never()).encode(any<String>(), any<String>())
        assertFalse("gone" in subValues)
        assertEquals(stored, subValues["a"])
        assertEquals("""["a"]""", mainValues["SUB_IDS"])
    }

    @Test
    fun aSwitchOfASubscriptionThatCannotBeReadWritesItAsTheListShowsIt() {
        mainValues["SUB_IDS"] = """["a"]"""
        subValues["a"] = "{"

        mockStatic(Log::class.java).use {
            assertTrue(MmkvManager.trySetSubscriptionEnabled("a", false))
        }

        assertEquals(false, JsonUtil.fromJson(subValues.getValue("a"), SubscriptionItem::class.java)?.enabled)
    }

    @Test
    fun aSwitchTheStorageRefusesIsToldAndLeavesTheSubscriptionAsItWas() {
        val stored = JsonUtil.toJson(SubscriptionItem(remarks = "Alpha"))
        subValues["a"] = stored
        refusedSubKeys += "a"

        mockStatic(Log::class.java).use {
            assertFalse(MmkvManager.trySetSubscriptionEnabled("a", false))
        }

        assertEquals(stored, subValues["a"])
    }

    @Test
    fun anUpdateTimeIsSetOnTheSubscriptionAsStoredWithoutTouchingTheList() {
        mainValues["SUB_IDS"] = """["a"]"""
        subValues["a"] = JsonUtil.toJson(SubscriptionItem(remarks = "Edited meanwhile", enabled = false))

        assertTrue(MmkvManager.trySetSubscriptionUpdated("a", 42L))

        val stored = JsonUtil.fromJson(subValues.getValue("a"), SubscriptionItem::class.java)
        assertEquals(42L, stored?.lastUpdated)
        assertEquals("Edited meanwhile", stored?.remarks)
        assertEquals(false, stored?.enabled)
        assertTrue(mainWrites.isEmpty())
        // Removed meanwhile: not stored again, nor listed.
        assertFalse(MmkvManager.trySetSubscriptionUpdated("gone", 42L))
        assertFalse("gone" in subValues)
        assertEquals("""["a"]""", mainValues["SUB_IDS"])
    }

    @Test
    fun anUpdateOfASubscriptionRemovedMeanwhileTakesTheProfilesItStoredAway() {
        // Removed during the download; the update then stored profiles p1 and p2 for it.
        mainValues["SUB_IDS"] = """["b"]"""
        mainValues["SUB_SERVERS_a"] = """["p1","p2"]"""
        mainValues["SELECTED_SERVER"] = "p1"

        assertFalse(MmkvManager.finishSubscriptionUpdate("a", 42L))

        assertFalse("a" in subValues)
        assertEquals("""["b"]""", mainValues["SUB_IDS"])
        assertEquals("[]", mainValues["SUB_SERVERS_a"])
        assertFalse("SELECTED_SERVER" in mainValues)
        verify(profiles).removeValuesForKeys(arrayOf("p1", "p2"))
        verify(raws).removeValuesForKeys(arrayOf("p1", "p2"))
        verify(affiliations).removeValuesForKeys(arrayOf("p1", "p2"))
        assertEquals(listOf("SUB_SERVERS_a" to true), mainWrites)
    }

    @Test
    fun anUpdateOfASubscriptionStillStoredEndsWithItsTimeAndItsProfilesKept() {
        mainValues["SUB_IDS"] = """["a"]"""
        mainValues["SUB_SERVERS_a"] = """["p1"]"""
        subValues["a"] = JsonUtil.toJson(SubscriptionItem(remarks = "Alpha"))

        assertTrue(MmkvManager.finishSubscriptionUpdate("a", 42L))

        assertEquals(42L, JsonUtil.fromJson(subValues.getValue("a"), SubscriptionItem::class.java)?.lastUpdated)
        assertEquals("""["p1"]""", mainValues["SUB_SERVERS_a"])
        verifyNoInteractions(profiles, raws, affiliations)
        assertTrue(mainWrites.isEmpty())
    }

    @Test
    fun theDefaultSubscriptionCanBeListedFirst() {
        mainValues["SUB_IDS"] = """["a","b"]"""

        assertEquals("d", MmkvManager.tryEncodeSubscription("d", SubscriptionItem(remarks = "Default"), listFirst = true))

        assertEquals(listOf("d", "a", "b"), MmkvManager.decodeSubsList())
    }

    @Test
    fun aNewSubscriptionWrittenWhileTheListIsEmptyKeepsTheStoredOnesListed() {
        // A list left empty, as by a version before it existed: it stands for every subscription stored.
        subValues["a"] = JsonUtil.toJson(SubscriptionItem(remarks = "Alpha"))

        assertEquals("d", MmkvManager.tryEncodeSubscription("d", SubscriptionItem(remarks = "Default"), listFirst = true))

        assertEquals(listOf("d", "a"), MmkvManager.decodeSubsList())
    }

    @Test
    fun anUpdateTimeLeavesAPayloadThatCannotBeReadAsItIs() {
        subValues["a"] = "{"

        mockStatic(Log::class.java).use {
            assertTrue(MmkvManager.trySetSubscriptionUpdated("a", 42L))
        }

        assertEquals("{", subValues["a"])
        verify(subs, never()).encode(any<String>(), any<String>())
    }

    @Test
    fun theSortAfterATestOrdersTheListAsStoredFastestFirstFailedAndUntestedLast() {
        mainValues["SUB_SERVERS_a"] = """["p1","p2","p3","p4"]"""
        tested("p1", 300)
        tested("p2", -1)
        tested("p3", 100)

        AngConfigManager.sortByTestResultsForSub("a")

        assertEquals("""["p3","p1","p2","p4"]""", mainValues["SUB_SERVERS_a"])
        assertEquals(listOf("SUB_SERVERS_a" to true), mainWrites)
    }

    @Test
    fun theSortAfterATestWritesNothingForAListAlreadyInOrderOrEmptiedByADelete() {
        mainValues["SUB_SERVERS_a"] = """["p1","p2"]"""
        tested("p1", 100)
        tested("p2", 200)
        // The subscription was removed during its test: its list is empty, and stays so.
        mainValues["SUB_SERVERS_b"] = "[]"

        AngConfigManager.sortByTestResultsForSub("a")
        AngConfigManager.sortByTestResultsForSub("b")

        assertTrue(mainWrites.isEmpty())
        assertEquals("[]", mainValues["SUB_SERVERS_b"])
    }

    @Test
    fun theRemovalAfterATestTakesTheFailedProfilesOfTheListAsStoredOutThenTheirPayloads() {
        mainValues["SUB_SERVERS_a"] = """["p1","p2","p3"]"""
        mainValues["SELECTED_SERVER"] = "p2"
        tested("p1", 100)
        tested("p2", -1)

        AngConfigManager.removeInvalidServer("a")

        assertEquals("""["p1","p3"]""", mainValues["SUB_SERVERS_a"])
        assertFalse("SELECTED_SERVER" in mainValues)
        verify(profiles).removeValuesForKeys(arrayOf("p2"))
        verify(raws).removeValuesForKeys(arrayOf("p2"))
        verify(affiliations).removeValuesForKeys(arrayOf("p2"))
        assertEquals(listOf("SUB_SERVERS_a" to true), mainWrites)
        // The results read, and the payloads gone, in one hold of both locks, the profile index lock taken first.
        assertEquals(listOf(true, true, true), affiliationReadsLocked)
        assertEquals(listOf(true), payloadRemovalsUnderResultLock)
        val order = inOrder(main, affiliations, profiles)
        order.verify(main).lock()
        order.verify(affiliations).lock()
        order.verify(profiles).removeValuesForKeys(arrayOf("p2"))
        order.verify(affiliations).unlock()
        order.verify(main).unlock()
    }

    @Test
    fun aRemovalAfterATestTheStorageRefusesLeavesTheProfilesListedAndStored() {
        val stored = """["p1","p2"]"""
        mainValues["SUB_SERVERS_a"] = stored
        tested("p2", -1)
        refusedMainKeys += "SUB_SERVERS_a"

        mockStatic(Log::class.java).use {
            assertFalse(MmkvManager.tryRemoveFailedServers("a"))
        }

        assertEquals(stored, mainValues["SUB_SERVERS_a"])
        verify(profiles, never()).removeValuesForKeys(any())
    }

    @Test
    fun aRemovalAfterATestOfAListEmptiedByADeleteWritesNothing() {
        mainValues["SUB_SERVERS_a"] = "[]"

        AngConfigManager.removeInvalidServer("a")

        assertTrue(mainWrites.isEmpty())
        verify(profiles, never()).removeValuesForKeys(any())
    }

    @Test
    fun aSortTheStorageRefusesIsToldAndLeavesTheListAsItWas() {
        val stored = """["p1","p2"]"""
        mainValues["SUB_SERVERS_a"] = stored
        refusedMainKeys += "SUB_SERVERS_a"

        mockStatic(Log::class.java).use {
            assertFalse(MmkvManager.trySortServerList("a") { if (it == "p2") 1L else 2L })
        }

        assertEquals(stored, mainValues["SUB_SERVERS_a"])
    }

    @Test
    fun aProfileIsMovedByTheTwoGuidsInTheListAsStoredUnderTheProfileIndexLock() {
        // p4 was stored by an update after the screen read the list.
        mainValues["SUB_SERVERS_a"] = """["p1","p2","p3","p4"]"""

        assertTrue(MmkvManager.tryMoveServer("a", "p3", "p1"))

        assertEquals("""["p3","p1","p2","p4"]""", mainValues["SUB_SERVERS_a"])
        assertEquals(listOf("SUB_SERVERS_a" to true), mainWrites)
        // Either gone: nothing to move.
        assertTrue(MmkvManager.tryMoveServer("a", "gone", "p1"))
        assertEquals(1, mainWrites.size)
    }

    @Test
    fun aMoveOfAProfileTheStorageRefusesIsToldAndLeavesTheListAsItWas() {
        val stored = """["p1","p2"]"""
        mainValues["SUB_SERVERS_a"] = stored
        refusedMainKeys += "SUB_SERVERS_a"

        mockStatic(Log::class.java).use {
            assertFalse(MmkvManager.tryMoveServer("a", "p2", "p1"))
        }

        assertEquals(stored, mainValues["SUB_SERVERS_a"])
    }

    @Test
    fun theMainScreensRemovalTakesAProfileWhoseTestFailedUnderBothLocksAndKeepsOneThatPassed() {
        mainValues["SUB_SERVERS_a"] = """["p1","p2"]"""
        stored("p1", "a")
        stored("p2", "a")
        tested("p1", 100)
        tested("p2", -1)

        assertEquals(0, MmkvManager.removeInvalidServer("p1"))
        clearInvocations(main, affiliations, profiles)
        affiliationReadsLocked.clear()
        assertEquals(1, MmkvManager.removeInvalidServer("p2"))

        assertEquals("""["p1"]""", mainValues["SUB_SERVERS_a"])
        verify(profiles).removeValuesForKeys(arrayOf("p2"))
        // Its result read, and its payloads gone, in one hold of both locks, the profile index lock taken first.
        assertEquals(listOf(true), affiliationReadsLocked)
        assertEquals(listOf(true), payloadRemovalsUnderResultLock)
        val order = inOrder(main, affiliations, profiles)
        order.verify(main).lock()
        order.verify(affiliations).lock()
        order.verify(profiles).removeValuesForKeys(arrayOf("p2"))
        order.verify(affiliations).unlock()
        order.verify(main).unlock()
        assertEquals(listOf("SUB_SERVERS_a" to true), mainWrites)
    }

    @Test
    fun theMainScreensRemovalOfEveryFailedProfileReadsEachStoredResultUnderTheLock() {
        mainValues["SUB_SERVERS_a"] = """["p1","p2","p3"]"""
        stored("p1", "a")
        stored("p2", "a")
        stored("p3", "a")
        tested("p1", 100)
        tested("p2", -1)
        tested("p3", 0)

        assertEquals(1, MmkvManager.removeInvalidServer(""))

        assertEquals("""["p1","p3"]""", mainValues["SUB_SERVERS_a"])
        verify(profiles).removeValuesForKeys(arrayOf("p2"))
        assertEquals(listOf(true, true, true), affiliationReadsLocked)
    }

    @Test
    fun theMainScreensRemovalKeepsAProfileWithoutAResultAndOneWhoseListTheStorageRefuses() {
        mainValues["SUB_SERVERS_a"] = """["p1","p2"]"""
        stored("p1", "a")
        stored("p2", "a")
        tested("p2", -1)
        refusedMainKeys += "SUB_SERVERS_a"

        assertEquals(0, MmkvManager.removeInvalidServer("p1"))
        mockStatic(Log::class.java).use {
            assertEquals(0, MmkvManager.removeInvalidServer("p2"))
        }

        assertEquals("""["p1","p2"]""", mainValues["SUB_SERVERS_a"])
        verify(profiles, never()).removeValuesForKeys(any())
    }

    @Test
    fun aTestResultIsWrittenAndClearedUnderTheLockOfTheTestResults() {
        MmkvManager.encodeServerTestDelayMillis("p1", 120)
        assertEquals(120L, JsonUtil.fromJson(affiliationValues.getValue("p1"), ServerAffiliationInfo::class.java)?.testDelayMillis)

        MmkvManager.clearAllTestDelayResults(listOf("p1"))
        assertEquals(0L, JsonUtil.fromJson(affiliationValues.getValue("p1"), ServerAffiliationInfo::class.java)?.testDelayMillis)

        assertEquals(listOf(true, true), affiliationWritesLocked)
        assertEquals(listOf(true, true), affiliationReadsLocked)
        val order = inOrder(affiliations)
        repeat(2) {
            order.verify(affiliations).lock()
            order.verify(affiliations).encode(eq("p1"), any<String>())
            order.verify(affiliations).unlock()
        }
        // Without the profile index lock, which a result does not need.
        verify(main, never()).lock()
    }

    @Test
    fun aTestResultTheStorageRefusesIsLoggedWrittenOrCleared() {
        tested("p1", 100)
        doReturn(false).whenever(affiliations).encode(any<String>(), any<String>())

        mockStatic(Log::class.java).use { log ->
            MmkvManager.encodeServerTestDelayMillis("p2", 120)
            MmkvManager.clearAllTestDelayResults(listOf("p1"))

            log.verify { Log.println(eq(Log.ERROR), any(), ArgumentMatchers.contains("refused the test result of profile p2")) }
            log.verify { Log.println(eq(Log.ERROR), any(), ArgumentMatchers.contains("refused the cleared test result of profile p1")) }
        }
        assertEquals(100L, JsonUtil.fromJson(affiliationValues.getValue("p1"), ServerAffiliationInfo::class.java)?.testDelayMillis)
    }

    companion object {
        /**
         * A handle as a subclass mock: MMKV's lock, unlock and removeValuesForKeys, which the profile index lock and the
         * removal of payloads call, are native methods, which the default inline mock maker cannot stand in for.
         */
        private fun handle(): MMKV = Mockito.mock(MMKV::class.java, Mockito.withSettings().mockMaker(MockMakers.SUBCLASS))

        private val main: MMKV = handle()
        private val subs: MMKV = handle()
        private val settings: MMKV = handle()
        private val profiles: MMKV = handle()
        private val raws: MMKV = handle()
        private val affiliations: MMKV = handle()

        @BeforeAll
        @JvmStatic
        fun initializeHandles() {
            mockStatic(MMKV::class.java).use {
                it.`when`<MMKV> { MMKV.mmkvWithID("MAIN", MMKV.MULTI_PROCESS_MODE) }.thenReturn(main)
                it.`when`<MMKV> { MMKV.mmkvWithID("SUB", MMKV.MULTI_PROCESS_MODE) }.thenReturn(subs)
                it.`when`<MMKV> { MMKV.mmkvWithID("SETTING", MMKV.MULTI_PROCESS_MODE) }.thenReturn(settings)
                it.`when`<MMKV> { MMKV.mmkvWithID("PROFILE_FULL_CONFIG", MMKV.MULTI_PROCESS_MODE) }.thenReturn(profiles)
                it.`when`<MMKV> { MMKV.mmkvWithID("SERVER_RAW", MMKV.MULTI_PROCESS_MODE) }.thenReturn(raws)
                it.`when`<MMKV> { MMKV.mmkvWithID("SERVER_AFF", MMKV.MULTI_PROCESS_MODE) }.thenReturn(affiliations)
                MmkvManager.decodeSubscriptions()
                MmkvManager.decodeSettingsString("test-initialize")
                MmkvManager.decodeServerConfig("test-initialize")
                MmkvManager.decodeServerRaw("test-initialize")
                MmkvManager.decodeServerAffiliationInfo("test-initialize")
            }
        }
    }
}
