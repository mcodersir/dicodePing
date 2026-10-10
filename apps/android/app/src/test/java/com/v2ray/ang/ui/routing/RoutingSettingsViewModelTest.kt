package com.v2ray.ang.ui.routing

import android.app.Application
import androidx.lifecycle.viewModelScope
import com.v2ray.ang.dto.entities.RulesetItem
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.async
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.mockito.kotlin.mock

class RoutingSettingsViewModelTest {

    /** The stored rules, in memory, with what the screen asked to store of them. */
    private class FakeSource : RoutingSettingsSource {
        var rules: List<RulesetItem> = emptyList()
        var loads = 0

        /** When set, a read waits for it, as one off the main thread takes its time. */
        var loadGate: CompletableDeferred<Unit>? = null

        /** When set, a write waits for it before it is done. */
        var writeGate: CompletableDeferred<Unit>? = null

        /** Each write as it started, and as it was done. */
        val started = mutableListOf<String>()
        val done = mutableListOf<String>()
        val updated = mutableListOf<RulesetItem>()
        val moved = mutableListOf<Pair<String, String>>()

        override suspend fun loadRules(): List<RulesetItem> {
            loads++
            loadGate?.await()
            return rules
        }

        override suspend fun updateRule(rule: RulesetItem) {
            started += "update ${rule.id}"
            writeGate?.await()
            updated += rule
            done += "update ${rule.id}"
        }

        override suspend fun moveRule(fromId: String, toId: String) {
            started += "move $fromId"
            writeGate?.await()
            moved += fromId to toId
            done += "move $fromId"
        }
    }

    private val source = FakeSource()
    private val a = RulesetItem(id = "a", remarks = "a", outboundTag = "proxy")
    private val b = RulesetItem(id = "b", remarks = "b", outboundTag = "direct")

    @OptIn(ExperimentalCoroutinesApi::class)
    @BeforeEach
    fun setUp() {
        Dispatchers.setMain(UnconfinedTestDispatcher())
        source.rules = listOf(a, b)
    }

    @OptIn(ExperimentalCoroutinesApi::class)
    @AfterEach
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun viewModel() = RoutingSettingsViewModel(mock<Application>(), source)

    @Test
    fun startsEmptyAndShowsWhatAReloadReads() {
        val viewModel = viewModel()
        assertTrue(viewModel.rulesetsFlow.value.isEmpty())

        viewModel.reload()

        assertEquals(listOf(a, b), viewModel.rulesetsFlow.value)
        assertEquals(1, source.loads)
    }

    @Test
    fun aRuleTurnedOffIsShownSoAtOnceAndStoredByItsId() {
        val viewModel = viewModel()
        viewModel.reload()
        val off = b.copy(enabled = false)

        viewModel.update(off)

        assertEquals(listOf(a, off), viewModel.rulesetsFlow.value)
        assertEquals(listOf(off), source.updated)
        // A rule the list does not hold changes nothing.
        viewModel.update(RulesetItem(id = "gone", remarks = "gone"))
        assertEquals(listOf(off), source.updated)
    }

    @Test
    fun aRuleMovedIsShownSoAtOnceAndStoredByTheIds() {
        val viewModel = viewModel()
        viewModel.reload()

        viewModel.move("a", "b")

        assertEquals(listOf(b, a), viewModel.rulesetsFlow.value)
        assertEquals(listOf("a" to "b"), source.moved)
        // A move to where the rule is, or of or to a rule the list does not hold, changes nothing.
        viewModel.move("a", "a")
        viewModel.move("gone", "a")
        viewModel.move("a", "gone")
        assertEquals(1, source.moved.size)
    }

    @Test
    fun nothingIsChangedWhileTheRulesAreReadAnew() {
        val viewModel = viewModel()
        viewModel.reload()
        val gate = CompletableDeferred<Unit>()
        source.loadGate = gate
        source.rules = listOf(a, b, RulesetItem(id = "c", remarks = "c"))

        viewModel.reload()
        viewModel.update(a.copy(enabled = false))
        viewModel.move("a", "b")
        gate.complete(Unit)

        // What was read is shown, and nothing stored over it from the list shown before.
        assertEquals(listOf("a", "b", "c"), viewModel.rulesetsFlow.value.map { it.id })
        assertTrue(source.started.isEmpty())
    }

    @Test
    fun writesAreDoneOneAtATimeInTheOrderAskedFor() {
        val viewModel = viewModel()
        viewModel.reload()
        val gate = CompletableDeferred<Unit>()
        source.writeGate = gate

        viewModel.update(a.copy(enabled = false))
        viewModel.move("a", "b")
        assertEquals(listOf("update a"), source.started)

        gate.complete(Unit)
        assertEquals(listOf("update a", "move a"), source.done)
    }

    @Test
    fun aReloadALaterOneReplacesShowsNothing() {
        val viewModel = viewModel()
        val gate = CompletableDeferred<Unit>()
        source.loadGate = gate

        viewModel.reload()
        source.loadGate = null
        source.rules = listOf(b)
        viewModel.reload()
        gate.complete(Unit)

        assertEquals(listOf(b), viewModel.rulesetsFlow.value)
    }

    @Test
    fun aChangeShownIsStoredThoughTheScreenClosesBeforeItsTurn() {
        val viewModel = viewModel()
        viewModel.reload()
        val gate = CompletableDeferred<Unit>()
        source.writeGate = gate

        viewModel.update(a.copy(enabled = false))
        viewModel.move("a", "b")
        // The screen closes, which ends the view model's scope, while one write waits and the other for its turn.
        viewModel.viewModelScope.cancel()
        gate.complete(Unit)

        assertEquals(listOf("update a", "move a"), source.done)
    }

    @Test
    fun theStoredRulesAreReadOnceWhatTheListAskedToStoreIsStored() = runBlocking {
        val viewModel = viewModel()
        viewModel.reload()
        val gate = CompletableDeferred<Unit>()
        source.writeGate = gate
        viewModel.update(a.copy(enabled = false))

        val read = async(Dispatchers.Unconfined) { viewModel.storedRules() }
        assertTrue(source.done.isEmpty())
        assertEquals(1, source.loads)
        gate.complete(Unit)

        assertEquals(listOf(a, b), read.await())
        assertEquals(listOf("update a"), source.done)
        assertEquals(2, source.loads)
    }
}
