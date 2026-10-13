package com.v2ray.ang.ui.subscription

import android.app.Application
import android.graphics.Bitmap
import androidx.lifecycle.viewModelScope
import com.v2ray.ang.AppConfig
import com.v2ray.ang.R
import com.v2ray.ang.dto.SubscriptionUpdateMessage
import com.v2ray.ang.dto.entities.SubscriptionCache
import com.v2ray.ang.extension.moveItem
import com.v2ray.ang.handler.AngConfigManager
import com.v2ray.ang.handler.SettingsChangeManager
import com.v2ray.ang.helper.MessageHelper
import com.v2ray.ang.ui.base.BaseViewModel
import com.v2ray.ang.util.LogUtil
import com.v2ray.ang.util.QRCodeDecoder
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.util.concurrent.atomic.AtomicInteger

class SubscriptionsViewModel(
    application: Application,
    private val source: SubscriptionListSource,
) : BaseViewModel(application) {
    private var qrCodeJob: Job? = null
    private val _qrCode = MutableStateFlow<Bitmap?>(null)
    internal val qrCode = _qrCode.asStateFlow()
    private val subscriptions: MutableList<SubscriptionCache> = mutableListOf()

    private val _subsFlow = MutableStateFlow(subscriptions.toList())
    val subsFlow: StateFlow<List<SubscriptionCache>> = _subsFlow.asStateFlow()

    /** PattNG: whether a delete is confirmed first, as the settings have it, read with the subscriptions, see [reload]. */
    private val _confirmRemove = MutableStateFlow(false)
    val confirmRemove: StateFlow<Boolean> = _confirmRemove.asStateFlow()

    /**
     * PattNG: a change the list asked for that the storage refused, still to be told once, by a number of its own, so that
     * a refusal set again right after the last one was told is told too; null when none, see [onRefusalShown]. The list
     * shows the subscriptions as stored by then.
     */
    private val _refused = MutableStateFlow<Int?>(null)
    val refused: StateFlow<Int?> = _refused.asStateFlow()

    /** PattNG: the number the last refusal got, see [refused]. */
    private val refusals = AtomicInteger()

    /** PattNG: the reads and writes of the stored subscriptions, off the main thread, one at a time, in the order asked for. */
    private val storage = Mutex()

    /** PattNG: the reading of the subscriptions the screen asked for last, see [reload]. */
    private var reloadJob: Job? = null

    /** PattNG: how many changes the list has asked for, so that a reading one of them overtook is not shown, see [reload]. */
    private var changes = 0

    /** PattNG: the writes asked for and not done yet, counted on the main thread, see [store]. */
    private var pendingWrites = 0

    /** PattNG: whether the screen is out of sight, see [onScreenHidden]. */
    private var hidden = false

    /** PattNG: whether a delete or a move stored while the screen was out of sight is still to be told, see [store]. */
    private var groupsChangedWhileHidden = false

    /** PattNG: the options of an update of the subscriptions, read off the main thread, see [loadUpdateOptions]; null until then. */
    private val _updateOptions = MutableStateFlow<SubscriptionUpdateOptions?>(null)
    val updateOptions: StateFlow<SubscriptionUpdateOptions?> = _updateOptions.asStateFlow()

    /** PattNG: the reads and writes of the update options, off the main thread, one at a time, in the order asked for. */
    private val optionsStorage = Mutex()

    /** PattNG: how many option changes the screen has asked for, so that a reading one of them overtook is not shown. */
    private var optionChanges = 0

    /** PattNG: the updates run here, which the screen shows its progress line for, see [showingProgress]. */
    private var updatesRunning = 0

    fun getAll(): List<SubscriptionCache> = subscriptions.toList()

    /**
     * Reads the subscriptions anew and shows them. PattNG: off the main thread, once what the list asked to store before
     * is stored, with whether a delete is confirmed first; a reload a later one replaces stops. A change asked for while
     * it runs is shown, and stored after this reading: the list is read again once it is, rather than this reading shown.
     */
    fun reload() {
        reloadJob?.cancel()
        val asked = changes
        reloadJob = viewModelScope.launch {
            val (loaded, confirm) = storage.withLock { source.loadSubscriptions() to source.confirmsRemove() }
            if (changes != asked) {
                reload()
                return@launch
            }
            _confirmRemove.value = confirm
            subscriptions.clear()
            subscriptions.addAll(loaded)
            _subsFlow.value = subscriptions.toList()
        }
    }

    /**
     * Deletes the subscription [subId] names, with its profiles: shown gone at once, and stored so, by its key, even when
     * the screen closes right after. PattNG: a delete the storage refused is told, see [refused].
     */
    fun remove(subId: String): Boolean {
        if (!subscriptions.removeAll { it.guid == subId }) return false
        changes++
        _subsFlow.value = subscriptions.toList()
        store(changesGroups = true) { source.deleteSubscription(subId) }
        return true
    }

    /**
     * Turns the subscription [subId] names on or off: shown at once, and stored so, by its key, on the subscription as
     * stored then, so that what an update wrote meanwhile, as its update time, stays. PattNG: a change the storage
     * refused is told, see [refused].
     */
    fun setEnabled(subId: String, enabled: Boolean) {
        val index = subscriptions.indexOfFirst { it.guid == subId }
        if (index < 0) return
        changes++
        val shown = subscriptions[index]
        subscriptions[index] = shown.copy(subscription = shown.subscription.copy(enabled = enabled))
        _subsFlow.value = subscriptions.toList()
        store(changesGroups = false) { source.setSubscriptionEnabled(subId, enabled) }
    }

    internal fun shareQRCode(url: String) {
        dismissQRCode()
        qrCodeJob = viewModelScope.launch {
            val bitmap = withContext(Dispatchers.Default) { QRCodeDecoder.createQRCode(url) }
            if (bitmap == null) toastError(R.string.toast_failure)
            _qrCode.value = bitmap
        }
    }

    internal fun dismissQRCode() {
        qrCodeJob?.cancel()
        qrCodeJob = null
        _qrCode.value = null
    }

    /**
     * Shows the subscription [fromId] names where the one [toId] names stands, and stores it there by their keys as well,
     * so that a subscription another writer listed meanwhile, as an import, is not written out of the list. PattNG: a
     * move the storage refused is told, see [refused].
     */
    fun move(fromId: String, toId: String) {
        if (!subscriptions.moveItem(subscriptions.indexOfFirst { it.guid == fromId }, subscriptions.indexOfFirst { it.guid == toId })) return
        changes++
        _subsFlow.value = subscriptions.toList()
        store(changesGroups = true) { source.moveSubscription(fromId, toId) }
    }

    /** PattNG: the refusal numbered [refusal] is told, see [refused]; a later one stays to be told. */
    fun onRefusalShown(refusal: Int) {
        _refused.update { if (it == refusal) null else it }
    }

    /**
     * PattNG: the screen goes out of sight, as when it closes, whoever closes it. The main screen sets its groups up again
     * when the list returns to it, on what the list stored by then; of a delete or a move stored while the list is out
     * of sight, it is told once the last write is done, see [SubscriptionListSource.announceGroupsChanged].
     */
    fun onScreenHidden() {
        hidden = true
    }

    /** PattNG: the screen is in sight again: what it stores now, its return to the main screen reports. */
    fun onScreenShown() {
        hidden = false
    }

    /**
     * PattNG: runs [write] in its turn, to its end even when the screen is gone by then, which a change shown is owed. A
     * write the storage refused is told, and the subscriptions are read anew, for the list to show them as stored. A
     * write that [changesGroups], stored while the screen is out of sight, is told to the main screen once the last
     * write is done, see [onScreenHidden].
     */
    private fun store(changesGroups: Boolean, write: suspend () -> Boolean) {
        pendingWrites++
        viewModelScope.launch {
            val taken = withContext(NonCancellable) {
                storage.withLock { write() }.also { taken ->
                    pendingWrites--
                    if (taken && changesGroups && hidden) groupsChangedWhileHidden = true
                    if (pendingWrites == 0 && groupsChangedWhileHidden) {
                        groupsChangedWhileHidden = false
                        source.announceGroupsChanged()
                    }
                }
            }
            if (!taken) {
                _refused.value = refusals.incrementAndGet()
                reload()
            }
        }
    }

    /**
     * PattNG: reads the options of an update off the main thread, once what the screen asked to store of them before is
     * stored, and shows them, see [updateOptions]; a reading an option change overtook is not shown, but done again.
     */
    fun loadUpdateOptions() {
        val asked = optionChanges
        viewModelScope.launch {
            val loaded = optionsStorage.withLock { source.loadUpdateOptions() }
            if (optionChanges != asked) {
                loadUpdateOptions()
                return@launch
            }
            _updateOptions.value = loaded
        }
    }

    /**
     * PattNG: turns the update option [option] on or off, as [value] says: shown at once, and stored so, in its turn,
     * even when the screen closes right after; a change the storage refused is told, see [refused], and the options
     * are read anew.
     */
    fun setUpdateOption(option: SubscriptionUpdateOption, value: Boolean) {
        val shown = _updateOptions.value ?: return
        optionChanges++
        _updateOptions.value = shown.with(option, value)
        viewModelScope.launch {
            val taken = withContext(NonCancellable) { optionsStorage.withLock { source.saveUpdateOption(option, value) } }
            if (!taken) {
                _refused.value = refusals.incrementAndGet()
                loadUpdateOptions()
            }
        }
    }

    /**
     * PattNG: the update options as stored once what the screen asked to store of them is, read off the main thread:
     * those an update reads, which the options shown differ from while a change is stored, or after one was refused.
     */
    suspend fun storedUpdateOptions(): SubscriptionUpdateOptions = optionsStorage.withLock { source.loadUpdateOptions() }

    /**
     * Updates the subscriptions as their options say, see [SubscriptionUpdateOptions.kind]. PattNG: by the options as
     * stored, see [storedUpdateOptions], since the update reads them too; the update chosen starts, and one run here
     * ends, even when the screen closes meanwhile, as one started at once did before.
     */
    fun updateSubscriptions() {
        viewModelScope.launch {
            try {
                val result = withContext(NonCancellable) {
                    when (storedUpdateOptions().kind) {
                        // If auto test is enabled, trigger background service for long-running task
                        SubscriptionUpdateKind.WITH_TESTS -> {
                            startUpdateWithTests()
                            null
                        }
                        // If only update is enabled, perform local update with UI loading state
                        SubscriptionUpdateKind.ONLY -> showingProgress {
                            withContext(Dispatchers.IO) {
                                AngConfigManager.updateConfigViaSubAll().also {
                                    // The main screen reloads the configs. Sent from here, the message also goes out when
                                    // this page closes before the update ends.
                                    if (it.configCount > 0) MessageHelper.sendMsg2UI(app, AppConfig.MSG_SERVERS_CHANGED, "")
                                }
                            }
                        }

                        SubscriptionUpdateKind.NONE -> null
                    }
                } ?: return@launch

                when {
                    result.successCount + result.failureCount + result.skipCount == 0 ->
                        toast(R.string.title_update_subscription_no_subscription)

                    result.successCount > 0 && result.failureCount + result.skipCount == 0 ->
                        toast(
                            getQuantityString(
                                R.plurals.title_update_config_count,
                                result.configCount,
                                result.configCount,
                            )
                        )

                    else ->
                        toast(getString(R.string.title_update_subscription_result, result.configCount, result.successCount, result.failureCount, result.skipCount))
                }
                reload()
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (e: Exception) {
                LogUtil.e(AppConfig.TAG, "Subscription update failed", e)
                toastError(R.string.toast_failure)
            }
        }
    }

    /**
     * PattNG: runs [work] while the screen shows its progress line, counted, so that an update ending, or a start that
     * shows none, does not hide the line of another that runs.
     */
    private suspend fun <T> showingProgress(work: suspend () -> T): T {
        updatesRunning++
        _isLoading.value = true
        try {
            return work()
        } finally {
            if (--updatesRunning == 0) _isLoading.value = false
        }
    }

    /**
     * Has the update service update, then test, the subscriptions that are on and have a URL, in the background. PattNG:
     * a start the system refused, as from the background, is told rather than said to run.
     */
    private suspend fun startUpdateWithTests() {
        SettingsChangeManager.makeSetupGroupTab()
        // PattNG: read off the main thread, once what the list asked to store before is stored.
        val subIds = storage.withLock { source.loadSubscriptions() }
            .filter { it.subscription.enabled && it.subscription.url.isNotEmpty() }
            .map { it.guid }

        if (subIds.isNotEmpty() &&
            !MessageHelper.sendMsg2SubscriptionService(app, SubscriptionUpdateMessage(AppConfig.MSG_SUB_UPDATE_START, false, subIds))
        ) {
            toastError(R.string.toast_failure)
            return
        }

        toast(R.string.subscription_updater_job_tips)
    }
}
