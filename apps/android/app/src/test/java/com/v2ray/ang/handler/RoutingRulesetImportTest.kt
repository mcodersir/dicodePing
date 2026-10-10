package com.v2ray.ang.handler

import com.v2ray.ang.dto.entities.RulesetItem
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Test

/** Unit tests for SettingsManager.rulesetsAfterImport and rulesetsWithOwnIds: what an import of routing rulesets leaves, and their ids. */
class RoutingRulesetImportTest {

    private val locked = RulesetItem(id = "locked", remarks = "kept", outboundTag = "direct", locked = true)
    private val unlocked = RulesetItem(id = "unlocked", remarks = "replaced", outboundTag = "proxy")

    @Test
    fun theLockedRulesetsStayFirstAndTheOthersGiveWayToTheImport() {
        val imported = listOf(RulesetItem(id = "a", remarks = "a"), RulesetItem(id = "b", remarks = "b"))

        assertEquals(listOf(locked) + imported, SettingsManager.rulesetsAfterImport(listOf(unlocked, locked), imported))
    }

    @Test
    fun theCopyOfALockedRulesetAnExportBringsBackIsLeftOutForTheLockedOne() {
        // As exported once it was locked, and edited since: the locked one stays as it is, once.
        val copy = locked.copy(remarks = "as exported")
        val other = RulesetItem(id = "a", remarks = "a")

        val after = SettingsManager.rulesetsAfterImport(listOf(locked, unlocked), listOf(other, copy))

        assertEquals(listOf(locked, other), after)
        assertEquals(after.map { it.id }.distinct(), after.map { it.id })
    }

    @Test
    fun rulesetsWithoutAnIdAreAllImportedThoughALockedOneHasNoneAndEachGetsOne() {
        val lockedWithoutId = locked.copy(id = "")
        val a = RulesetItem(remarks = "a")
        val b = RulesetItem(remarks = "b")
        val ids = generateSequence(1) { it + 1 }.map { "new-$it" }.iterator()

        assertEquals(
            listOf(lockedWithoutId.copy(id = "new-1"), a.copy(id = "new-2"), b.copy(id = "new-3")),
            SettingsManager.rulesetsAfterImport(listOf(lockedWithoutId), listOf(a, b)) { ids.next() }
        )
    }

    @Test
    fun withNothingStoredTheImportIsTakenAsItIs() {
        val imported = listOf(locked, RulesetItem(id = "a", remarks = "a"))

        assertEquals(imported, SettingsManager.rulesetsAfterImport(null, imported))
        assertEquals(imported, SettingsManager.rulesetsAfterImport(emptyList(), imported))
    }

    @Test
    fun theCopyOfALockedRulesetExportedBeforeItWasLockedIsLeftOutToo() {
        val copy = locked.copy(remarks = "as exported", locked = false)

        assertEquals(listOf(locked), SettingsManager.rulesetsAfterImport(listOf(locked), listOf(copy)))
    }

    @Test
    fun aRulesetWithTheIdOfAnUnlockedOneIsImportedInItsPlace() {
        // The unlocked one gives way to the import, so its copy is no second rule with its id.
        val copy = unlocked.copy(remarks = "as exported")

        assertEquals(listOf(locked, copy), SettingsManager.rulesetsAfterImport(listOf(locked, unlocked), listOf(copy)))
    }

    @Test
    fun anImportRepeatingAnIdWithinItselfKeepsOneOfAWholeRepeatAndGivesOtherContentAnIdOfItsOwn() {
        val a = RulesetItem(id = "a", remarks = "a")
        val other = RulesetItem(id = "a", remarks = "other")

        assertEquals(listOf(a, other.copy(id = "new")), SettingsManager.rulesetsAfterImport(null, listOf(a, a, other)) { "new" })
    }

    @Test
    fun eachRulesetGetsAnIdOfItsOwn() {
        val a = RulesetItem(id = "a", remarks = "a")
        val edited = a.copy(remarks = "a, edited")
        val noId = RulesetItem(remarks = "no id")
        val ids = generateSequence(1) { it + 1 }.map { "new-$it" }.iterator()

        // One repeating a ruleset before it whole goes; one with its id and other content, or with none, gets a new one.
        assertEquals(
            listOf(a, edited.copy(id = "new-1"), noId.copy(id = "new-2")),
            SettingsManager.rulesetsWithOwnIds(listOf(a, a, edited, noId)) { ids.next() }
        )
        // Null when each has its own already, so that nothing is stored again.
        assertNull(SettingsManager.rulesetsWithOwnIds(listOf(a, RulesetItem(id = "b"))))
        assertNull(SettingsManager.rulesetsWithOwnIds(emptyList()))
    }

    @Test
    fun aListStoredWithTheCopyOfALockedRulesetIsPutRight() {
        // As an import stored it before it left the copy out: the copy, locked as well, goes.
        assertEquals(listOf(locked, unlocked), SettingsManager.rulesetsWithOwnIds(listOf(locked, unlocked, locked)))
    }

    @Test
    fun aWholeRepeatGoesThoughTheRulesetItRepeatsGotANewId() {
        val a = RulesetItem(id = "x", remarks = "a")
        val b = RulesetItem(id = "x", remarks = "b")
        val noId = RulesetItem(remarks = "no id")
        val ids = generateSequence(1) { it + 1 }.map { "new-$it" }.iterator()

        // As a locked rule, edited since, with three copies of it as exported: the copies are one.
        assertEquals(
            listOf(a, b.copy(id = "new-1"), noId.copy(id = "new-2")),
            SettingsManager.rulesetsWithOwnIds(listOf(a, b, b, b, noId, noId)) { ids.next() }
        )
    }
}
