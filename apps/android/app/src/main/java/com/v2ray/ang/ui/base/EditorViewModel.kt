package com.v2ray.ang.ui.base

import android.app.Application
import androidx.annotation.StringRes
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/** PattNG: what the save or the delete of an editor screen ends with, for the screen to act on once, see [EditorViewModel.outcome]. */
sealed interface EditorOutcome {
    /** Written, as [key]: the guid of the profile, the key of the subscription, or the id of the routing rule. */
    data class Saved(val key: String) : EditorOutcome

    /** Not written, for [message], whose arguments are [args]: the screen tells it and stays open. */
    data class Refused(@StringRes val message: Int, val args: List<String> = emptyList()) : EditorOutcome

    /** Deleted: the screen closes. */
    data object Deleted : EditorOutcome
}

/** PattNG: whether the screen closes on this outcome, telling the screen it returns to what was written. */
val EditorOutcome?.closesScreen: Boolean
    get() = this is EditorOutcome.Saved || this == EditorOutcome.Deleted

/**
 * PattNG: the save and the delete of an editor screen that reads and writes off the main thread. They run here rather
 * than in the activity's lifecycle scope, which ends when the activity is recreated, as on a rotation: a save cut off
 * there was lost, or written with nothing told, and the screen, still open on what it was opened with, stored a second
 * copy at the next tap. Here one runs at a time, a delete waits for a save that runs and says what the screen closes
 * on, nothing starts once a delete has unless it is refused, and the [outcome] reaches whichever activity shows the
 * screen when it comes. A view model of a screen keeps what its saves stored as, for the next one to write over. The screen
 * waits for the save or the delete that runs, and for the outcome it closes on, before it closes, see [leaveScreen].
 */
abstract class EditorViewModel(application: Application) : BaseViewModel(application) {

    private val _outcome = MutableStateFlow<EditorOutcome?>(null)

    /** The outcome the screen has not acted on yet, see [onOutcomeHandled]; null while there is none. */
    val outcome: StateFlow<EditorOutcome?> = _outcome.asStateFlow()

    private var saveJob: Job? = null
    private var deleteJob: Job? = null
    private var deleting = false
    private var left = false

    /** A save that ended once a delete was asked for, held for the delete to say what the screen closes on, see [launchDelete]. */
    private var heldSave: EditorOutcome.Saved? = null

    /** Whether a save or a delete runs. */
    val isBusy: Boolean
        get() = saveJob?.isActive == true || deleteJob?.isActive == true

    private val _busy = MutableStateFlow(false)

    /** [isBusy], for the screen to observe: Back waits for what runs, see [leaveScreen]. */
    val busy: StateFlow<Boolean> = _busy.asStateFlow()

    /**
     * Runs [save], unless a save or a delete runs, a delete has started, or the screen is left. What it ends with goes
     * to [outcome]; null, as when the screen shows a field's error itself, goes nowhere.
     */
    protected fun launchSave(save: suspend () -> EditorOutcome?) {
        if (isBusy || deleting || left) return
        saveJob = viewModelScope.launch {
            val result = save() ?: return@launch
            if (deleting && result is EditorOutcome.Saved) heldSave = result else _outcome.value = result
        }
        watch(saveJob)
    }

    /**
     * Runs [delete], unless a delete has started or the screen is left; then [outcome] is [EditorOutcome.Deleted]. A save
     * that runs ends first, so that it cannot write back what is deleted; what it saved, or what a save before it saved
     * and the screen has not acted on yet, is held meanwhile. A delete [refuse] gives a refusal for, or one the storage
     * refuses, which gives the refusal it ends with, goes to [outcome] in place of [EditorOutcome.Deleted]: the screen
     * stays open for saves and deletes, unless a save was held, which the screen closes on once it has acted on the
     * refusal, telling the screen it returns to what was saved. The outcomes live here, so a rotation meanwhile loses none.
     */
    protected fun launchDelete(refuse: (suspend () -> EditorOutcome.Refused?)? = null, delete: suspend () -> EditorOutcome.Refused?) {
        if (deleting || left) return
        deleting = true
        (_outcome.value as? EditorOutcome.Saved)?.let { pending -> if (_outcome.compareAndSet(pending, null)) heldSave = pending }
        deleteJob = viewModelScope.launch {
            saveJob?.join()
            val refusal = refuse?.invoke() ?: delete()
            val saved = heldSave
            heldSave = null
            when {
                refusal == null -> _outcome.value = EditorOutcome.Deleted

                saved == null -> {
                    deleting = false
                    _outcome.value = refusal
                }

                else -> {
                    _outcome.value = refusal
                    _outcome.first { it == null }
                    deleting = false
                    _outcome.value = saved
                }
            }
        }
        watch(deleteJob)
    }

    /**
     * PattNG: what [load] reads as the screen opens, off the main thread, for the screen to show its form on; null until
     * then, while the screen shows that it waits, see [EditorLoading]. Read once, and kept while the activity is
     * recreated.
     */
    protected fun <T : Any> openedWith(load: suspend () -> T): StateFlow<T?> {
        val opened = MutableStateFlow<T?>(null)
        viewModelScope.launch { opened.value = load() }
        return opened.asStateFlow()
    }

    /** Keeps [busy] as [isBusy] says, now that [job] has started, and once it ends. */
    private fun watch(job: Job?) {
        _busy.value = isBusy
        job?.invokeOnCompletion { _busy.value = isBusy }
    }

    /**
     * Whether the screen may close now: not while a save or a delete runs, which closes it once it has written, with
     * what it did for the screen it returns to, nor while the outcome it closes on waits for the screen to act on it;
     * left before, the write would go untold, and that screen would neither show it nor restart the running profile
     * with it. Once the screen may close, no save or delete starts any more.
     */
    fun leaveScreen(): Boolean {
        if (isBusy || _outcome.value.closesScreen) return false
        left = true
        return true
    }

    /**
     * The screen has acted on [handled], the outcome it was shown: cleared, unless another one came meanwhile, as a save
     * that ends right after a delete was refused, which the screen then acts on in its turn.
     */
    fun onOutcomeHandled(handled: EditorOutcome? = _outcome.value) {
        if (handled != null) _outcome.compareAndSet(handled, null)
    }
}
