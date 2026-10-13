package com.v2ray.ang.ui.base

import android.app.Application
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
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.mockito.kotlin.mock

class EditorViewModelTest {

    private class Editor : EditorViewModel(mock<Application>()) {
        fun save(work: suspend () -> EditorOutcome?) = launchSave(work)
        fun delete(refuse: (suspend () -> EditorOutcome.Refused?)? = null, work: suspend () -> Unit) =
            launchDelete(refuse) {
                work()
                null
            }

        /** A delete that ends in what [work] gives: the refusal of the storage, or null once deleted. */
        fun deleteOrRefuse(work: suspend () -> EditorOutcome.Refused?) = launchDelete(delete = work)
    }

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

    @Test
    fun startsIdleWithNoOutcome() {
        val editor = Editor()

        assertNull(editor.outcome.value)
        assertFalse(editor.isBusy)
    }

    @Test
    fun aSaveEndsInWhatItGivesAndASaveThatGivesNothingInNoOutcome() {
        val editor = Editor()

        editor.save { null }
        assertNull(editor.outcome.value)

        editor.save { EditorOutcome.Saved("guid") }
        assertEquals(EditorOutcome.Saved("guid"), editor.outcome.value)
    }

    @Test
    fun theScreenActsOnAnOutcomeOnce() {
        val editor = Editor()
        editor.save { EditorOutcome.Refused(1, listOf("name")) }
        assertEquals(EditorOutcome.Refused(1, listOf("name")), editor.outcome.value)

        editor.onOutcomeHandled()

        assertNull(editor.outcome.value)
    }

    @Test
    fun oneSaveRunsAtATime() {
        val editor = Editor()
        val gate = CompletableDeferred<Unit>()
        var second = false
        editor.save { gate.await(); EditorOutcome.Saved("first") }

        assertTrue(editor.isBusy)
        editor.save { second = true; EditorOutcome.Saved("second") }
        assertFalse(second)

        gate.complete(Unit)
        assertFalse(editor.isBusy)
        assertEquals(EditorOutcome.Saved("first"), editor.outcome.value)

        // Once it is done, the next one runs.
        editor.save { second = true; EditorOutcome.Saved("second") }
        assertTrue(second)
        assertEquals(EditorOutcome.Saved("second"), editor.outcome.value)
    }

    @Test
    fun aDeleteWaitsForTheSaveThatRunsAndClosesTheScreenItself() {
        val editor = Editor()
        val write = CompletableDeferred<Unit>()
        val order = mutableListOf<String>()
        editor.save { write.await(); order += "written"; EditorOutcome.Saved("guid") }

        // Confirmed while the save runs: the delete is not dropped, and runs once the save has ended, so that the save
        // writes nothing back after it; what the save saved is held, the delete closing the screen.
        editor.delete { order += "deleted" }
        write.complete(Unit)

        assertEquals(listOf("written", "deleted"), order)
        assertEquals(EditorOutcome.Deleted, editor.outcome.value)
    }

    @Test
    fun aDeleteTheStorageRefusesAfterASaveLeavesTheSaveToCloseTheScreenOn() {
        val editor = Editor()
        val write = CompletableDeferred<Unit>()
        editor.save { write.await(); EditorOutcome.Saved("guid") }

        editor.deleteOrRefuse { EditorOutcome.Refused(2) }
        write.complete(Unit)
        assertEquals(EditorOutcome.Refused(2), editor.outcome.value)
        assertFalse(editor.leaveScreen())

        editor.onOutcomeHandled()
        assertEquals(EditorOutcome.Saved("guid"), editor.outcome.value)
    }

    @Test
    fun aDeleteAskedWhileASavedWaitsForTheScreenHoldsIt() {
        val editor = Editor()
        editor.save { EditorOutcome.Saved("guid") }

        // Asked for before the screen acted on the save: the save is held, and the delete closes the screen.
        var deleted = false
        editor.delete { deleted = true }
        assertTrue(deleted)
        assertEquals(EditorOutcome.Deleted, editor.outcome.value)

        // Refused, the save it held is what the screen closes on, once it has told the refusal.
        val other = Editor()
        other.save { EditorOutcome.Saved("guid") }
        other.delete(refuse = { EditorOutcome.Refused(1) }) { error("a refused delete does not run") }
        assertEquals(EditorOutcome.Refused(1), other.outcome.value)
        other.onOutcomeHandled()
        assertEquals(EditorOutcome.Saved("guid"), other.outcome.value)
    }

    @Test
    fun aRefusedDeleteLeavesTheScreenOpenForSavesAndDeletes() {
        val editor = Editor()
        var deleted = false
        editor.delete(refuse = { EditorOutcome.Refused(1) }) { deleted = true }
        assertEquals(EditorOutcome.Refused(1), editor.outcome.value)
        assertFalse(deleted)

        editor.onOutcomeHandled()
        editor.save { EditorOutcome.Saved("guid") }
        assertEquals(EditorOutcome.Saved("guid"), editor.outcome.value)
        editor.onOutcomeHandled()
        editor.delete(refuse = { null }) { deleted = true }
        assertTrue(deleted)
        assertEquals(EditorOutcome.Deleted, editor.outcome.value)
    }

    @Test
    fun anOutcomeThatCameAfterTheOneActedOnStaysForTheScreen() {
        val editor = Editor()
        editor.delete(refuse = { EditorOutcome.Refused(1) }) { error("a refused delete does not run") }
        val shown = editor.outcome.value

        // A save ends before the screen has acted on the refusal it was shown: acting on it leaves the save's outcome.
        editor.save { EditorOutcome.Saved("guid") }
        editor.onOutcomeHandled(shown)
        assertEquals(EditorOutcome.Saved("guid"), editor.outcome.value)

        editor.onOutcomeHandled(EditorOutcome.Saved("guid"))
        assertNull(editor.outcome.value)
    }

    @Test
    fun aRefusedDeleteLetsASaveThatRunsEndAndTheScreenCloseOnIt() {
        val editor = Editor()
        val lookup = CompletableDeferred<Unit>()
        var written = false
        editor.save { lookup.await(); written = true; EditorOutcome.Saved("guid") }

        editor.delete(refuse = { EditorOutcome.Refused(1) }) { error("a refused delete does not run") }
        // The delete waits for the save, which another save waits for in its turn.
        assertNull(editor.outcome.value)
        assertTrue(editor.isBusy)

        lookup.complete(Unit)
        assertTrue(written)
        assertEquals(EditorOutcome.Refused(1), editor.outcome.value)
        // Told the refusal, the screen closes on the save, which it tells the screen it returns to.
        editor.onOutcomeHandled()
        assertEquals(EditorOutcome.Saved("guid"), editor.outcome.value)
        assertFalse(editor.isBusy)
    }

    @Test
    fun nothingStartsOnceADeleteHasAndItEndsInDeleted() {
        val editor = Editor()
        val gate = CompletableDeferred<Unit>()
        var deletes = 0
        var saved = false
        editor.delete { deletes++; gate.await() }

        editor.save { saved = true; EditorOutcome.Saved("guid") }
        editor.delete { deletes++ }
        gate.complete(Unit)
        assertEquals(EditorOutcome.Deleted, editor.outcome.value)

        // Not after it either: the save would write back what it deleted.
        editor.onOutcomeHandled()
        editor.save { saved = true; EditorOutcome.Saved("guid") }
        editor.delete { deletes++ }

        assertFalse(saved)
        assertEquals(1, deletes)
        assertNull(editor.outcome.value)
    }

    @Test
    fun theScreenMayNotCloseWhileASaveRunsAndOnceItMayNothingStarts() {
        val editor = Editor()
        val write = CompletableDeferred<Unit>()
        editor.save { write.await(); EditorOutcome.Saved("guid") }

        // Back waits: the save ends in its outcome, which closes the screen telling what it wrote, once acted on.
        assertFalse(editor.leaveScreen())
        write.complete(Unit)
        assertEquals(EditorOutcome.Saved("guid"), editor.outcome.value)
        assertFalse(editor.leaveScreen())
        editor.onOutcomeHandled()
        assertTrue(editor.leaveScreen())

        var started = false
        editor.save { started = true; EditorOutcome.Saved("guid") }
        editor.delete { started = true }
        assertFalse(started)
    }

    @Test
    fun theScreenMayNotCloseWhileADeleteRuns() {
        val editor = Editor()
        val gate = CompletableDeferred<Unit>()
        editor.delete { gate.await() }

        assertFalse(editor.leaveScreen())
        gate.complete(Unit)
        assertEquals(EditorOutcome.Deleted, editor.outcome.value)
        assertFalse(editor.leaveScreen())
        editor.onOutcomeHandled()
        assertTrue(editor.leaveScreen())
    }

    @Test
    fun aRefusalWaitingToBeToldDoesNotHoldTheScreen() {
        val editor = Editor()

        editor.save { EditorOutcome.Refused(1) }

        assertTrue(editor.leaveScreen())
    }

    @Test
    fun aDeleteTheStorageRefusesEndsInItsRefusalAndTheScreenStaysForSavesAndDeletes() {
        val editor = Editor()

        editor.deleteOrRefuse { EditorOutcome.Refused(2) }
        assertEquals(EditorOutcome.Refused(2), editor.outcome.value)

        editor.onOutcomeHandled()
        editor.save { EditorOutcome.Saved("guid") }
        assertEquals(EditorOutcome.Saved("guid"), editor.outcome.value)

        editor.onOutcomeHandled()
        var deleted = false
        editor.delete { deleted = true }
        assertTrue(deleted)
        assertEquals(EditorOutcome.Deleted, editor.outcome.value)
    }

    @Test
    fun busyFollowsTheSaveAndTheDeleteThatRun() {
        val editor = Editor()
        assertFalse(editor.busy.value)

        val save = CompletableDeferred<Unit>()
        editor.save { save.await(); EditorOutcome.Saved("guid") }
        assertTrue(editor.busy.value)
        save.complete(Unit)
        assertFalse(editor.busy.value)

        // One that ends at once leaves it as it was.
        editor.save { null }
        assertFalse(editor.busy.value)

        // A refused delete waits for a save that runs, and holds it until the screen has acted on the refusal, the save
        // then left for the screen to close on.
        val next = CompletableDeferred<Unit>()
        editor.save { next.await(); EditorOutcome.Saved("guid") }
        editor.delete(refuse = { EditorOutcome.Refused(1) }) {}
        assertTrue(editor.busy.value)
        next.complete(Unit)
        assertTrue(editor.busy.value)
        editor.onOutcomeHandled()
        assertFalse(editor.busy.value)

        // A delete holds it until it has deleted.
        editor.onOutcomeHandled()
        val delete = CompletableDeferred<Unit>()
        editor.delete { delete.await() }
        assertTrue(editor.busy.value)
        delete.complete(Unit)
        assertFalse(editor.busy.value)
    }
}
