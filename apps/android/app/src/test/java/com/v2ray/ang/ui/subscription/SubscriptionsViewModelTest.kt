package com.v2ray.ang.ui.subscription

import android.app.Application
import androidx.lifecycle.viewModelScope
import com.v2ray.ang.dto.entities.SubscriptionCache
import com.v2ray.ang.dto.entities.SubscriptionItem
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.async
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.mockito.kotlin.mock

class SubscriptionsViewModelTest {

    /** The stored subscriptions, in memory, with what the list asked to store of them. */
    private class FakeSource : SubscriptionListSource {
        var stored: List<SubscriptionCache> = emptyList()
        var confirmRemove = false
        var loads = 0

        /** When set, a read waits for it, as one off the main thread takes its time. */
        var loadGate: CompletableDeferred<Unit>? = null

        /** When set, a write waits for it before it is done. */
        var writeGate: CompletableDeferred<Unit>? = null

        /** When set, the storage refuses every write: nothing is written. */
        var refuseWrites = false

        /** Each write as it started, and as it was done. */
        val started = mutableListOf<String>()
        val done = mutableListOf<String>()

        /** How many times the main screen was told the groups changed, and how many times it was by the start of each write. */
        var announcements = 0
        val announcedAtStart = mutableListOf<Int>()

        override fun announceGroupsChanged() {
            announcements++
        }

        var options = SubscriptionUpdateOptions()
        var optionLoads = 0

        /** When set, a read of the options waits for it; when set, a write of one waits for it. */
        var optionLoadGate: CompletableDeferred<Unit>? = null
        var optionWriteGate: CompletableDeferred<Unit>? = null

        /** Each option write as it started, and as it was done. */
        val optionsStarted = mutableListOf<String>()
        val optionsDone = mutableListOf<String>()

        override suspend fun loadUpdateOptions(): SubscriptionUpdateOptions {
            optionLoads++
            optionLoadGate?.await()
            return options
        }

        override suspend fun saveUpdateOption(option: SubscriptionUpdateOption, value: Boolean): Boolean {
            optionsStarted += "$option $value"
            optionWriteGate?.await()
            if (refuseWrites) return false
            options = options.with(option, value)
            optionsDone += "$option $value"
            return true
        }

        override suspend fun loadSubscriptions(): List<SubscriptionCache> {
            loads++
            loadGate?.await()
            // Fresh copies, as real reads give.
            return stored.map { it.copy(subscription = it.subscription.copy()) }
        }

        override suspend fun confirmsRemove(): Boolean = confirmRemove

        override suspend fun deleteSubscription(subId: String): Boolean = write("delete $subId") {
            stored = stored.filter { it.guid != subId }
        }

        override suspend fun setSubscriptionEnabled(subId: String, enabled: Boolean): Boolean = write("enable $subId $enabled") {
            stored = stored.map { if (it.guid == subId) it.copy(subscription = it.subscription.copy(enabled = enabled)) else it }
        }

        override suspend fun moveSubscription(fromId: String, toId: String): Boolean = write("move $fromId $toId") {
            val ids = stored.map { it.guid }
            val moved = stored.toMutableList().apply { add(ids.indexOf(toId), removeAt(ids.indexOf(fromId))) }
            stored = moved
        }

        private suspend fun write(what: String, change: () -> Unit): Boolean {
            started += what
            announcedAtStart += announcements
            writeGate?.await()
            if (refuseWrites) return false
            change()
            done += what
            return true
        }
    }

    private val source = FakeSource()
    private val a = SubscriptionCache("a", SubscriptionItem(remarks = "Alpha"))
    private val b = SubscriptionCache("b", SubscriptionItem(remarks = "Beta"))
    private val c = SubscriptionCache("c", SubscriptionItem(remarks = "Gamma"))

    @OptIn(ExperimentalCoroutinesApi::class)
    @BeforeEach
    fun setUp() {
        Dispatchers.setMain(UnconfinedTestDispatcher())
        source.stored = listOf(a, b, c)
    }

    @OptIn(ExperimentalCoroutinesApi::class)
    @AfterEach
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun viewModel() = SubscriptionsViewModel(mock<Application>(), source)

    private fun SubscriptionsViewModel.shown(): List<String> = subsFlow.value.map { it.guid }

    /** What the list shows: each subscription's key, and whether it is on. */
    private fun List<SubscriptionCache>.described(): List<String> = map { "${it.guid}:${it.subscription.enabled}" }

    @Test
    fun theSubscriptionsAreShownOnceReadWithWhetherADeleteIsConfirmedFirst() {
        source.confirmRemove = true
        val gate = CompletableDeferred<Unit>()
        source.loadGate = gate
        val viewModel = viewModel()

        viewModel.reload()
        assertTrue(viewModel.subsFlow.value.isEmpty())
        assertFalse(viewModel.confirmRemove.value)
        gate.complete(Unit)

        assertEquals(listOf("a", "b", "c"), viewModel.shown())
        assertTrue(viewModel.confirmRemove.value)
    }

    @Test
    fun aDeleteShowsTheSubscriptionGoneAtOnceAndStoresItByItsKey() {
        val viewModel = viewModel()
        viewModel.reload()
        val gate = CompletableDeferred<Unit>()
        source.writeGate = gate

        assertTrue(viewModel.remove("b"))

        // Shown before it is stored.
        assertEquals(listOf("a", "c"), viewModel.shown())
        assertTrue(source.done.isEmpty())
        gate.complete(Unit)
        assertEquals(listOf("delete b"), source.done)
        assertNull(viewModel.refused.value)
        // One delete asked for a subscription no longer shown asks nothing.
        assertFalse(viewModel.remove("b"))
        assertEquals(listOf("delete b"), source.started)
    }

    @Test
    fun aDeleteTheStorageRefusesIsToldOnceAndTheListShowsTheSubscriptionsAsStored() {
        val viewModel = viewModel()
        viewModel.reload()
        source.refuseWrites = true

        viewModel.remove("b")

        val refusal = checkNotNull(viewModel.refused.value)
        assertEquals(listOf("a", "b", "c"), viewModel.shown())
        assertEquals(2, source.loads)
        viewModel.onRefusalShown(refusal)
        assertNull(viewModel.refused.value)
    }

    @Test
    fun aRefusalSetAgainRightAfterTheLastWasToldIsToldToo() {
        val viewModel = viewModel()
        viewModel.reload()
        source.refuseWrites = true

        viewModel.remove("b")
        val first = checkNotNull(viewModel.refused.value)
        viewModel.setEnabled("a", false)
        val second = checkNotNull(viewModel.refused.value)

        // A number of its own, so the screen tells it, and the first one's late acknowledgement does not clear it.
        assertNotEquals(first, second)
        viewModel.onRefusalShown(first)
        assertEquals(second, viewModel.refused.value)
        viewModel.onRefusalShown(second)
        assertNull(viewModel.refused.value)
    }

    @Test
    fun aSwitchTurnsTheSubscriptionOnOrOffAtOnceAndStoresItByItsKey() {
        val viewModel = viewModel()
        viewModel.reload()
        val before = viewModel.subsFlow.value
        val gate = CompletableDeferred<Unit>()
        source.writeGate = gate

        viewModel.setEnabled("a", false)

        // Shown before it is stored, as a new list of a new subscription: the list shown before is left as it was.
        assertFalse(viewModel.subsFlow.value.first { it.guid == "a" }.subscription.enabled)
        assertTrue(before.first { it.guid == "a" }.subscription.enabled)
        assertTrue(source.done.isEmpty())
        gate.complete(Unit)
        assertEquals(listOf("enable a false"), source.done)
    }

    @Test
    fun aSwitchTheStorageRefusesIsToldAndTheListShowsTheSubscriptionAsStored() {
        val viewModel = viewModel()
        viewModel.reload()
        source.refuseWrites = true

        viewModel.setEnabled("a", false)

        assertNotNull(viewModel.refused.value)
        assertTrue(viewModel.subsFlow.value.first { it.guid == "a" }.subscription.enabled)
    }

    @Test
    fun aMoveShowsTheNewOrderAtOnceAndStoresItByTheKeys() {
        val viewModel = viewModel()
        viewModel.reload()
        val gate = CompletableDeferred<Unit>()
        source.writeGate = gate

        viewModel.move("c", "a")

        // Shown before it is stored, as the dragged list needs.
        assertEquals(listOf("c", "a", "b"), viewModel.shown())
        assertTrue(source.done.isEmpty())
        gate.complete(Unit)
        assertEquals(listOf("move c a"), source.done)
        assertEquals(listOf("c", "a", "b"), source.stored.map { it.guid })
    }

    @Test
    fun aMoveTheStorageRefusesIsToldAndTheListShowsTheStoredOrder() {
        val viewModel = viewModel()
        viewModel.reload()
        source.refuseWrites = true

        viewModel.move("c", "a")

        assertNotNull(viewModel.refused.value)
        assertEquals(listOf("a", "b", "c"), viewModel.shown())
    }

    @Test
    fun aMoveOfASubscriptionNotShownAsksNothing() {
        val viewModel = viewModel()
        viewModel.reload()

        viewModel.move("gone", "a")
        viewModel.move("a", "a")
        viewModel.setEnabled("gone", false)

        assertTrue(source.started.isEmpty())
        assertEquals(listOf("a", "b", "c"), viewModel.shown())
    }

    /**
     * Asks for [change] while the list is read anew, and checks that it is shown at once, as [shownAfter] describes it,
     * and stored after that reading, which is never shown: the list is read again after the change.
     */
    private fun changeWhileTheListIsRead(change: (SubscriptionsViewModel) -> Unit, shownAfter: List<String>, stored: String) {
        val viewModel = viewModel()
        viewModel.reload()
        val gate = CompletableDeferred<Unit>()
        source.loadGate = gate
        viewModel.reload()

        change(viewModel)
        // Everything the list shows from now on.
        val seen = mutableListOf<List<String>>()
        val collector = CoroutineScope(Dispatchers.Unconfined).launch {
            viewModel.subsFlow.collect { seen += it.described() }
        }
        assertEquals(listOf(shownAfter), seen)
        // Stored after the reading that runs.
        assertTrue(source.started.isEmpty())
        source.loadGate = null
        gate.complete(Unit)
        collector.cancel()

        assertEquals(listOf(stored), source.done)
        assertEquals(3, source.loads)
        // The reading taken before the change was stored never showed.
        assertTrue(seen.all { it == shownAfter }, "shown: $seen")
    }

    @Test
    fun aDeleteAskedForWhileTheListIsReadIsShownStoredAndTheListReadAgainAfterIt() =
        changeWhileTheListIsRead({ it.remove("a") }, listOf("b:true", "c:true"), "delete a")

    @Test
    fun aSwitchAskedForWhileTheListIsReadIsShownStoredAndTheListReadAgainAfterIt() =
        changeWhileTheListIsRead({ it.setEnabled("b", false) }, listOf("a:true", "b:false", "c:true"), "enable b false")

    @Test
    fun aMoveAskedForWhileTheListIsReadIsShownStoredAndTheListReadAgainAfterIt() =
        changeWhileTheListIsRead({ it.move("c", "a") }, listOf("c:true", "a:true", "b:true"), "move c a")

    @Test
    fun theWritesRunOneAtATimeInTheOrderAskedForAndAReadWaitsForThem() {
        val viewModel = viewModel()
        viewModel.reload()
        val gate = CompletableDeferred<Unit>()
        source.writeGate = gate

        viewModel.move("c", "a")
        viewModel.setEnabled("b", false)
        assertEquals(listOf("move c a"), source.started)
        viewModel.reload()
        assertEquals(1, source.loads)
        gate.complete(Unit)

        assertEquals(listOf("move c a", "enable b false"), source.done)
        assertEquals(2, source.loads)
        assertEquals(listOf("c", "a", "b"), viewModel.shown())
    }

    @Test
    fun aChangeShownIsStoredEvenWhenTheScreenClosesBeforeItIsWritten() {
        val viewModel = viewModel()
        viewModel.reload()
        val gate = CompletableDeferred<Unit>()
        source.writeGate = gate

        // One being written, one waiting for its turn.
        viewModel.remove("a")
        viewModel.move("c", "b")
        viewModel.viewModelScope.cancel()
        gate.complete(Unit)

        assertEquals(listOf("delete a", "move c b"), source.done)
    }

    @Test
    fun aReloadALaterOneReplacesShowsNothing() {
        val gate = CompletableDeferred<Unit>()
        source.loadGate = gate
        val viewModel = viewModel()
        viewModel.reload()

        source.loadGate = null
        source.stored = listOf(c)
        viewModel.reload()
        // Shown at once: the reading it replaced stopped, and holds the storage no longer.
        assertEquals(listOf("c"), viewModel.shown())
        gate.complete(Unit)

        assertEquals(listOf("c"), viewModel.shown())
        assertEquals(2, source.loads)
    }

    @Test
    fun anEmptyListIsShownEmpty() {
        val viewModel = viewModel()
        viewModel.reload()
        source.stored = emptyList()

        viewModel.reload()

        assertTrue(viewModel.subsFlow.value.isEmpty())
        assertEquals(2, source.loads)
    }

    @Test
    fun aDeleteOrAMoveStoredWhileTheScreenIsOutOfSightIsToldToTheMainScreenOnceTheLastWriteIsDone() {
        val viewModel = viewModel()
        viewModel.reload()
        val gate = CompletableDeferred<Unit>()
        source.writeGate = gate

        viewModel.remove("a")
        viewModel.move("c", "b")
        viewModel.setEnabled("b", false)
        viewModel.onScreenHidden()
        assertEquals(0, source.announcements)
        gate.complete(Unit)

        assertEquals(listOf("delete a", "move c b", "enable b false"), source.done)
        // Told once, after the last write: not before the move and the switch were stored.
        assertEquals(listOf(0, 0, 0), source.announcedAtStart)
        assertEquals(1, source.announcements)
    }

    @Test
    fun aWriteStoredOnceTheScreenIsInSightAgainIsLeftToItsReturn() {
        val viewModel = viewModel()
        viewModel.reload()
        val gate = CompletableDeferred<Unit>()
        source.writeGate = gate

        viewModel.remove("a")
        viewModel.onScreenHidden()
        viewModel.onScreenShown()
        gate.complete(Unit)

        assertEquals(listOf("delete a"), source.done)
        assertEquals(0, source.announcements)
    }

    @Test
    fun nothingIsToldForWhatIsStoredWhileTheScreenIsOpenForASwitchOrForARefusal() {
        val viewModel = viewModel()
        viewModel.reload()

        // Stored while the screen is open: its return reports it.
        viewModel.remove("a")
        viewModel.move("c", "b")
        val gate = CompletableDeferred<Unit>()
        source.writeGate = gate
        // A switch changes no group.
        viewModel.setEnabled("b", false)
        viewModel.onScreenHidden()
        gate.complete(Unit)
        assertEquals(0, source.announcements)

        // A delete refused changes nothing.
        val refusal = viewModel()
        refusal.reload()
        val held = CompletableDeferred<Unit>()
        source.writeGate = held
        source.refuseWrites = true
        refusal.remove("b")
        refusal.onScreenHidden()
        held.complete(Unit)
        assertEquals(0, source.announcements)
    }

    @Test
    fun theUpdateOptionsAreShownOnceRead() {
        source.options = SubscriptionUpdateOptions(setOf(SubscriptionUpdateOption.UPDATE))
        val gate = CompletableDeferred<Unit>()
        source.optionLoadGate = gate
        val viewModel = viewModel()

        viewModel.loadUpdateOptions()
        assertEquals(null, viewModel.updateOptions.value)
        gate.complete(Unit)

        assertEquals(SubscriptionUpdateOptions(setOf(SubscriptionUpdateOption.UPDATE)), viewModel.updateOptions.value)
    }

    @Test
    fun anUpdateOptionIsShownAtOnceAndStoredInItsTurn() {
        val viewModel = viewModel()
        viewModel.loadUpdateOptions()
        val gate = CompletableDeferred<Unit>()
        source.optionWriteGate = gate

        viewModel.setUpdateOption(SubscriptionUpdateOption.TEST_AFTER, true)
        viewModel.setUpdateOption(SubscriptionUpdateOption.SORT_AFTER_TEST, true)

        assertEquals(
            SubscriptionUpdateOptions(setOf(SubscriptionUpdateOption.TEST_AFTER, SubscriptionUpdateOption.SORT_AFTER_TEST)),
            viewModel.updateOptions.value,
        )
        assertTrue(source.optionsDone.isEmpty())
        // One at a time: the second waits for the first.
        assertEquals(listOf("TEST_AFTER true"), source.optionsStarted)
        gate.complete(Unit)
        assertEquals(listOf("TEST_AFTER true", "SORT_AFTER_TEST true"), source.optionsDone)
    }

    @Test
    fun anUpdateOptionTheStorageRefusesIsToldAndTheOptionsReadAgain() {
        val viewModel = viewModel()
        viewModel.loadUpdateOptions()
        source.refuseWrites = true

        viewModel.setUpdateOption(SubscriptionUpdateOption.UPDATE, true)

        assertNotNull(viewModel.refused.value)
        assertEquals(SubscriptionUpdateOptions(), viewModel.updateOptions.value)
        assertEquals(2, source.optionLoads)
    }

    @Test
    fun anOptionChangeAskedForWhileTheOptionsAreReadIsShownAndTheyAreReadAgainAfterIt() {
        val viewModel = viewModel()
        viewModel.loadUpdateOptions()
        val gate = CompletableDeferred<Unit>()
        source.optionLoadGate = gate
        viewModel.loadUpdateOptions()

        viewModel.setUpdateOption(SubscriptionUpdateOption.UPDATE, true)
        val changed = SubscriptionUpdateOptions(setOf(SubscriptionUpdateOption.UPDATE))
        // Everything shown from now on.
        val seen = mutableListOf<SubscriptionUpdateOptions?>()
        val collector = CoroutineScope(Dispatchers.Unconfined).launch {
            viewModel.updateOptions.collect { seen += it }
        }
        source.optionLoadGate = null
        gate.complete(Unit)
        collector.cancel()

        // The reading taken before the change was stored never showed; the one after it did.
        assertEquals(listOf("UPDATE true"), source.optionsDone)
        assertEquals(3, source.optionLoads)
        assertTrue(seen.all { it == changed }, "shown: $seen")
        assertEquals(changed, viewModel.updateOptions.value)
    }

    @Test
    fun noOptionChangeIsAskedBeforeTheOptionsAreRead() {
        val viewModel = viewModel()

        viewModel.setUpdateOption(SubscriptionUpdateOption.UPDATE, true)

        assertEquals(null, viewModel.updateOptions.value)
        assertTrue(source.optionsDone.isEmpty())
    }

    @Test
    fun theOptionsAreReadOnceWhatTheScreenAskedToStoreOfThemIsStored() {
        val viewModel = viewModel()
        viewModel.loadUpdateOptions()
        val gate = CompletableDeferred<Unit>()
        source.optionWriteGate = gate
        viewModel.setUpdateOption(SubscriptionUpdateOption.UPDATE, true)

        viewModel.loadUpdateOptions()
        // Read after the write, which is held.
        assertEquals(1, source.optionLoads)
        gate.complete(Unit)

        assertEquals(2, source.optionLoads)
        assertEquals(SubscriptionUpdateOptions(setOf(SubscriptionUpdateOption.UPDATE)), viewModel.updateOptions.value)
    }

    @Test
    fun anUpdateDoesWhatItsOptionsSayTheTestBeforeTheUpdateAlone() {
        assertEquals(SubscriptionUpdateKind.NONE, SubscriptionUpdateOptions().kind)
        assertEquals(SubscriptionUpdateKind.ONLY, SubscriptionUpdateOptions(setOf(SubscriptionUpdateOption.UPDATE)).kind)
        assertEquals(SubscriptionUpdateKind.WITH_TESTS, SubscriptionUpdateOptions(setOf(SubscriptionUpdateOption.TEST_AFTER)).kind)
        assertEquals(
            SubscriptionUpdateKind.WITH_TESTS,
            SubscriptionUpdateOptions(setOf(SubscriptionUpdateOption.UPDATE, SubscriptionUpdateOption.TEST_AFTER)).kind,
        )
        // Removing and sorting only follow a test.
        assertEquals(
            SubscriptionUpdateKind.NONE,
            SubscriptionUpdateOptions(setOf(SubscriptionUpdateOption.REMOVE_INVALID_AFTER_TEST, SubscriptionUpdateOption.SORT_AFTER_TEST)).kind,
        )
    }

    @Test
    fun theStoredUpdateOptionsAreReadOnceTheChangesAskedForAreStored() = runBlocking {
        val viewModel = viewModel()
        viewModel.loadUpdateOptions()
        val gate = CompletableDeferred<Unit>()
        source.optionWriteGate = gate
        viewModel.setUpdateOption(SubscriptionUpdateOption.TEST_AFTER, true)

        val stored = async(Dispatchers.Unconfined) { viewModel.storedUpdateOptions() }
        // Read after the change, which is held.
        assertFalse(stored.isCompleted)
        gate.complete(Unit)

        assertEquals(SubscriptionUpdateOptions(setOf(SubscriptionUpdateOption.TEST_AFTER)), stored.await())
    }

    @Test
    fun theStoredUpdateOptionsAreTheStoredOnesNotTheShownAfterARefusal() = runBlocking {
        val viewModel = viewModel()
        viewModel.loadUpdateOptions()
        val gate = CompletableDeferred<Unit>()
        source.optionWriteGate = gate
        source.refuseWrites = true
        viewModel.setUpdateOption(SubscriptionUpdateOption.TEST_AFTER, true)
        // Shown on, while the write the storage refuses runs.
        assertEquals(SubscriptionUpdateOptions(setOf(SubscriptionUpdateOption.TEST_AFTER)), viewModel.updateOptions.value)

        val stored = async(Dispatchers.Unconfined) { viewModel.storedUpdateOptions() }
        gate.complete(Unit)

        assertEquals(SubscriptionUpdateOptions(), stored.await())
    }
}
