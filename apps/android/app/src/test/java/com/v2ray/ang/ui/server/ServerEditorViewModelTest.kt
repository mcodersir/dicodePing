package com.v2ray.ang.ui.server

import android.app.Application
import com.v2ray.ang.R
import com.v2ray.ang.dto.entities.ProfileItem
import com.v2ray.ang.enums.EConfigType
import com.v2ray.ang.ui.base.EditorOutcome
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertSame
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.mockito.kotlin.mock

class ServerEditorViewModelTest {

    private val source = FakeProfileEditorSource()

    @OptIn(ExperimentalCoroutinesApi::class)
    @BeforeEach
    fun setUp() {
        Dispatchers.setMain(UnconfinedTestDispatcher())
    }

    @OptIn(ExperimentalCoroutinesApi::class)
    @AfterEach
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun viewModel(guid: String = "", subscriptionId: String? = null, serviceRunning: Boolean = false, type: EConfigType = EConfigType.VLESS) =
        ServerEditorViewModel(mock<Application>(), source, guid, subscriptionId, type, serviceRunning)

    private fun vless(name: String, subscription: String = "") = ProfileItem.create(EConfigType.VLESS).apply {
        remarks = name
        server = "203.0.113.7"
        serverPort = "443"
        subscriptionId = subscription
    }

    @Test
    fun startsWithNoOutcome() {
        assertNull(viewModel().outcome.value)
    }

    @Test
    fun aNewProfileIsStoredAsBuiltIntoTheSubscriptionAndALaterSaveWritesOverIt() {
        val viewModel = viewModel(subscriptionId = "sub")
        val built = vless("new")

        viewModel.save(built)

        assertEquals(EditorOutcome.Saved("guid-1"), viewModel.outcome.value)
        assertSame(built, source.stored.getValue("guid-1"))
        assertEquals("sub", built.subscriptionId)

        // As when the screen, recreated before it closed, is saved again: the profile it stored is written over.
        viewModel.onOutcomeHandled()
        viewModel.save(vless("renamed"))

        assertEquals(EditorOutcome.Saved("guid-1"), viewModel.outcome.value)
        assertEquals(listOf("guid-1", "guid-1"), source.saves)
        assertEquals(setOf("guid-1"), source.stored.keys)
        assertEquals("renamed", source.stored.getValue("guid-1").remarks)
    }

    @Test
    fun aStoredProfileIsWrittenOverAndKeepsItsSubscription() {
        source.stored["vless-guid"] = vless("old", subscription = "own")
        val viewModel = viewModel(guid = "vless-guid", subscriptionId = "sub")

        // The screen builds the profile on the one it was opened on, which carries its subscription.
        viewModel.save(vless("edited", subscription = "own"))

        assertEquals(EditorOutcome.Saved("vless-guid"), viewModel.outcome.value)
        assertEquals(listOf("vless-guid"), source.saves)
        assertEquals("edited", source.stored.getValue("vless-guid").remarks)
        assertEquals("own", source.stored.getValue("vless-guid").subscriptionId)
    }

    @Test
    fun aProfileSavedOutsideASubscriptionGetsNone() {
        val viewModel = viewModel()

        viewModel.save(vless("new"))

        assertEquals("", source.stored.getValue("guid-1").subscriptionId)
    }

    @Test
    fun aSecondTapWhileTheSaveRunsSavesNothingMore() {
        val gate = CompletableDeferred<Unit>()
        source.saveGate = gate
        val viewModel = viewModel()

        viewModel.save(vless("new"))
        viewModel.save(vless("new"))
        gate.complete(Unit)

        assertEquals(listOf("guid-1"), source.saves)
        assertEquals(EditorOutcome.Saved("guid-1"), viewModel.outcome.value)
    }

    @Test
    fun theScreenMayNotCloseWhileTheSaveRuns() {
        val gate = CompletableDeferred<Unit>()
        source.saveGate = gate
        val viewModel = viewModel()

        viewModel.save(vless("new"))
        assertFalse(viewModel.leaveScreen())
        gate.complete(Unit)

        assertEquals(EditorOutcome.Saved("guid-1"), viewModel.outcome.value)
        assertFalse(viewModel.leaveScreen())
        viewModel.onOutcomeHandled()
        assertTrue(viewModel.leaveScreen())
    }

    @Test
    fun aDeleteDeletesTheProfileUnlessTheAppRunsOnIt() {
        source.stored["vless-guid"] = vless("old")
        source.selected = "vless-guid"
        val viewModel = viewModel(guid = "vless-guid")

        viewModel.delete()
        assertEquals(EditorOutcome.Refused(R.string.toast_action_not_allowed), viewModel.outcome.value)
        assertTrue(source.deletes.isEmpty())

        // Told, the screen stays open, and deletes once the app runs on another profile.
        viewModel.onOutcomeHandled()
        source.selected = "other"
        viewModel.delete()
        assertEquals(EditorOutcome.Deleted, viewModel.outcome.value)
        assertEquals(listOf("vless-guid"), source.deletes)
        assertTrue(source.stored.isEmpty())
    }

    @Test
    fun aDeleteWaitsForTheSaveThatRunsSoThatItDoesNotWriteTheProfileBack() {
        source.stored["vless-guid"] = vless("old")
        val gate = CompletableDeferred<Unit>()
        source.saveGate = gate
        val viewModel = viewModel(guid = "vless-guid")

        viewModel.save(vless("edited"))
        viewModel.delete()
        gate.complete(Unit)

        assertEquals(EditorOutcome.Deleted, viewModel.outcome.value)
        assertEquals(listOf("vless-guid"), source.deletes)
        assertTrue(source.stored.isEmpty())
    }

    @Test
    fun aNewProfileNeverStoredHasNothingToDelete() {
        val viewModel = viewModel()

        viewModel.delete()

        assertNull(viewModel.outcome.value)
        assertTrue(source.deletes.isEmpty())
    }

    @Test
    fun aWriteTheStorageRefusesIsToldAndTheScreenStaysForAnotherTry() {
        source.refuseWrites = true
        val viewModel = viewModel()

        viewModel.save(vless("new"))

        assertEquals(EditorOutcome.Refused(R.string.toast_failure), viewModel.outcome.value)
        assertTrue(source.stored.isEmpty())

        // Tried again once the storage takes it: under the guid the first try got, so that what that one may have stored
        // part of is written over, not stored a second time.
        viewModel.onOutcomeHandled()
        source.refuseWrites = false
        viewModel.save(vless("new"))

        assertEquals(EditorOutcome.Saved("guid-1"), viewModel.outcome.value)
        assertEquals(listOf("guid-1", "guid-1"), source.saves)
        assertEquals(setOf("guid-1"), source.stored.keys)
    }

    @Test
    fun aDeleteTheStorageRefusesIsToldAndLeavesTheProfile() {
        source.stored["vless-guid"] = vless("old")
        source.refuseDeletes = true
        val viewModel = viewModel(guid = "vless-guid")

        viewModel.delete()

        assertEquals(EditorOutcome.Refused(R.string.toast_failure), viewModel.outcome.value)
        assertEquals(setOf("vless-guid"), source.stored.keys)
    }

    @Test
    fun theAppRunsOnTheProfileWhenItRunsAndTheProfileIsTheOneSelected() {
        source.stored["vless-guid"] = vless("old")
        source.selected = "vless-guid"

        assertEquals(true, viewModel(guid = "vless-guid", serviceRunning = true).isRunning.value)
        // Not when the app runs on another, nor when it runs not at all, nor for a new profile.
        source.selected = "other"
        assertEquals(false, viewModel(guid = "vless-guid", serviceRunning = true).isRunning.value)
        source.selected = "vless-guid"
        assertEquals(false, viewModel(guid = "vless-guid").isRunning.value)
        assertEquals(false, viewModel(serviceRunning = true).isRunning.value)
    }

    @Test
    fun whetherTheAppRunsOnTheProfileIsUnknownUntilRead() {
        val gate = CompletableDeferred<Unit>()
        source.selectedGate = gate
        source.selected = "vless-guid"
        val viewModel = viewModel(guid = "vless-guid", serviceRunning = true)

        assertNull(viewModel.isRunning.value)
        gate.complete(Unit)
        assertEquals(true, viewModel.isRunning.value)
    }

    @Test
    fun theProfileIsReadOffTheMainThreadBeforeTheScreenShowsIt() {
        source.stored["stored"] = vless("stored", subscription = "sub")
        val gate = CompletableDeferred<Unit>()
        source.openGate = gate

        val viewModel = viewModel(guid = "stored")
        assertNull(viewModel.opened.value)
        gate.complete(Unit)

        assertEquals(source.stored.getValue("stored"), viewModel.opened.value)
    }

    @Test
    fun aNewProfileOrOneGoneOpensAsANewOneOfTheScreensType() {
        val new = viewModel(type = EConfigType.TROJAN).opened.value
        assertEquals(EConfigType.TROJAN, new?.configType)
        assertEquals("", new?.remarks)

        val gone = viewModel(guid = "gone", type = EConfigType.SOCKS).opened.value
        assertEquals(EConfigType.SOCKS, gone?.configType)
        assertEquals("", gone?.remarks)
    }
}
