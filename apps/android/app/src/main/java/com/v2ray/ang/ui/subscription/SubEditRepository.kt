package com.v2ray.ang.ui.subscription

import com.v2ray.ang.AngApplication
import com.v2ray.ang.AppConfig
import com.v2ray.ang.dto.ByName
import com.v2ray.ang.dto.entities.ProfileItem
import com.v2ray.ang.dto.entities.SubscriptionCache
import com.v2ray.ang.dto.entities.SubscriptionItem
import com.v2ray.ang.enums.EConfigType
import com.v2ray.ang.handler.MmkvManager
import com.v2ray.ang.handler.SettingsChangeManager
import com.v2ray.ang.handler.SettingsManager
import com.v2ray.ang.handler.SubscriptionUpdater
import com.v2ray.ang.helper.MessageHelper
import com.v2ray.ang.ui.server.ProfileNameSource
import com.v2ray.ang.ui.server.storedProfileNames
import com.v2ray.ang.ui.server.withStoredProfileNames
import com.v2ray.ang.util.LogUtil
import com.v2ray.ang.util.Utils
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * PattNG: where the subscription editor reads what it opens on, finds the profiles it names and stores, or deletes, its
 * subscription.
 */
interface SubEditSource : ProfileNameSource {
    /** The subscription [subId] names, read off the main thread; null when it names none. */
    suspend fun loadSubscription(subId: String): SubscriptionItem?

    /** The names of the stored profiles but those of [excluded] types, read off the main thread, see [storedProfileNames]. */
    suspend fun profileNames(excluded: Set<EConfigType>): List<String>

    /** Whether a delete is confirmed first, as the settings have it, read off the main thread. */
    suspend fun confirmsRemove(): Boolean

    /**
     * Stores the subscription [subId] names with [edit] made on it as stored then, so that what a background update
     * wrote meanwhile, as its update time, stays, or, when [subId] is blank, a new one; schedules its updates as it
     * has them now; gives the key it is stored as, or null, with nothing stored, when the storage refused it.
     */
    suspend fun saveSubscription(subId: String, edit: (SubscriptionItem) -> Unit): String?

    /** Deletes the subscription [subId] names, with its profiles. False, with nothing deleted, when the storage refused it. */
    suspend fun deleteSubscription(subId: String): Boolean
}

/** PattNG: an option of an update of the subscriptions the list starts, by the setting that holds it. */
enum class SubscriptionUpdateOption(val key: String) {
    UPDATE(AppConfig.PREF_UPDATE_SUBSCRIPTION),
    TEST_AFTER(AppConfig.PREF_AUTO_TEST_AFTER_UPDATE_SUBSCRIPTION),
    REMOVE_INVALID_AFTER_TEST(AppConfig.PREF_AUTO_REMOVE_INVALID_AFTER_TEST),
    SORT_AFTER_TEST(AppConfig.PREF_AUTO_SORT_AFTER_TEST),
}

/** PattNG: what an update of the subscriptions the list starts does, see [SubscriptionUpdateOptions.kind]. */
enum class SubscriptionUpdateKind {
    /** The subscriptions are updated, then their profiles tested, in the background, by the update service. */
    WITH_TESTS,

    /** The subscriptions are updated while the list shows that it runs. */
    ONLY,

    /** Nothing: neither the update nor the test is on. */
    NONE,
}

/** PattNG: the options of an update of the subscriptions: those [on]; the others are off. */
data class SubscriptionUpdateOptions(val on: Set<SubscriptionUpdateOption> = emptySet()) {
    operator fun get(option: SubscriptionUpdateOption): Boolean = option in on

    /** These options with [option] turned on or off, as [value] says. */
    fun with(option: SubscriptionUpdateOption, value: Boolean) = copy(on = if (value) on + option else on - option)

    /** What an update does with these options: with the test on, it runs in the background, with the update alone, here. */
    val kind: SubscriptionUpdateKind
        get() = when {
            this[SubscriptionUpdateOption.TEST_AFTER] -> SubscriptionUpdateKind.WITH_TESTS
            this[SubscriptionUpdateOption.UPDATE] -> SubscriptionUpdateKind.ONLY
            else -> SubscriptionUpdateKind.NONE
        }
}

/**
 * PattNG: where the subscription list reads the subscriptions and stores what it changes of them, each off the main
 * thread and by the key of the subscription: deletes one, turns one on or off, or moves one; and the options of an
 * update it starts. A change the storage refused is told.
 */
interface SubscriptionListSource {
    /** The subscriptions, in their order. */
    suspend fun loadSubscriptions(): List<SubscriptionCache>

    /** Whether a delete is confirmed first, as the settings have it. */
    suspend fun confirmsRemove(): Boolean

    /** Deletes the subscription [subId] names, with its profiles. False, with nothing deleted, when the storage refused it. */
    suspend fun deleteSubscription(subId: String): Boolean

    /**
     * Turns the subscription [subId] names on or off, as stored then, so that what an update wrote meanwhile stays;
     * nothing when it is gone. False, with nothing written, when the storage refused it.
     */
    suspend fun setSubscriptionEnabled(subId: String, enabled: Boolean): Boolean

    /**
     * Moves the subscription [fromId] names to where the one [toId] names stands, in the list as stored then; nothing
     * when either is gone. False, with nothing moved, when the storage refused it.
     */
    suspend fun moveSubscription(fromId: String, toId: String): Boolean

    /**
     * Tells the main screen the groups of the subscriptions changed, for it to set them up again at once: for a change
     * stored after the list closed, which the list's return to it no longer reports.
     */
    fun announceGroupsChanged()

    /** The options of an update of the subscriptions, as the settings have them. */
    suspend fun loadUpdateOptions(): SubscriptionUpdateOptions

    /**
     * Stores [value] as the setting of [option], as a switch of the settings does, the screens that depend on it told.
     * False, with nothing written, when the storage refused it.
     */
    suspend fun saveUpdateOption(option: SubscriptionUpdateOption, value: Boolean): Boolean
}

/**
 * PattNG: [SubEditSource] and [SubscriptionListSource] over [MmkvManager] and [SettingsManager], which own the
 * subscriptions: it only moves their reads and writes off the main thread, and lets the editor's and the list's view
 * models be tested without them.
 */
class SubEditRepository : SubEditSource, SubscriptionListSource {

    override suspend fun <T> withProfileNames(takes: (ProfileItem) -> Boolean, check: (find: (String) -> ByName<ProfileItem>) -> T): T =
        withStoredProfileNames(takes, check)

    override suspend fun loadSubscription(subId: String): SubscriptionItem? =
        withContext(Dispatchers.IO) { MmkvManager.decodeSubscription(subId) }

    override suspend fun profileNames(excluded: Set<EConfigType>): List<String> = storedProfileNames(excluded)

    override suspend fun confirmsRemove(): Boolean =
        withContext(Dispatchers.IO) { MmkvManager.decodeSettingsBool(AppConfig.PREF_CONFIRM_REMOVE, false) }

    override suspend fun loadSubscriptions(): List<SubscriptionCache> =
        withContext(Dispatchers.IO) { MmkvManager.decodeSubscriptions() }

    // A refusal is logged by tryEncodeSubscription; its updates are scheduled only once it is stored.
    override suspend fun saveSubscription(subId: String, edit: (SubscriptionItem) -> Unit): String? =
        withContext(Dispatchers.IO) {
            // A new subscription gets its key here, so that its updates are scheduled under it.
            val key = subId.ifBlank { Utils.getUuid() }
            val subItem = MmkvManager.decodeSubscription(key) ?: SubscriptionItem()
            edit(subItem)
            MmkvManager.tryEncodeSubscription(key, subItem) ?: return@withContext null
            SubscriptionUpdater.syncOne(subId = key)
            SettingsChangeManager.makeSetupGroupTab()
            key
        }

    // A refusal is logged by MmkvManager.tryRemoveSubscription.
    override suspend fun deleteSubscription(subId: String): Boolean =
        withContext(Dispatchers.IO) {
            SettingsManager.tryRemoveSubscriptionWithDefault(subId).also { removed ->
                if (removed) SettingsChangeManager.makeSetupGroupTab()
            }
        }

    // A refusal is logged by MmkvManager.trySetSubscriptionEnabled.
    override suspend fun setSubscriptionEnabled(subId: String, enabled: Boolean): Boolean =
        withContext(Dispatchers.IO) { MmkvManager.trySetSubscriptionEnabled(subId, enabled) }

    // A refusal is logged by MmkvManager.tryMoveSubscription.
    override suspend fun moveSubscription(fromId: String, toId: String): Boolean =
        withContext(Dispatchers.IO) {
            MmkvManager.tryMoveSubscription(fromId, toId).also { moved ->
                if (moved) SettingsChangeManager.makeSetupGroupTab()
            }
        }

    // The main screen sets its groups up again on this message, as after an update, see MainViewModel.
    override fun announceGroupsChanged() {
        MessageHelper.sendMsg2UI(AngApplication.application, AppConfig.MSG_SERVERS_CHANGED, "")
    }

    override suspend fun loadUpdateOptions(): SubscriptionUpdateOptions =
        withContext(Dispatchers.IO) {
            SubscriptionUpdateOptions(SubscriptionUpdateOption.entries.filter { MmkvManager.decodeSettingsBool(it.key, false) }.toSet())
        }

    // As MmkvManager.rememberMmkvBool stores a switch of the settings, which the dialog used before.
    override suspend fun saveUpdateOption(option: SubscriptionUpdateOption, value: Boolean): Boolean =
        withContext(Dispatchers.IO) {
            MmkvManager.encodeSettings(option.key, value).also { taken ->
                if (taken) {
                    SettingsChangeManager.notifySettingChanged(option.key)
                } else {
                    LogUtil.e(AppConfig.TAG, "Subscriptions: the storage refused the update option ${option.key}")
                }
            }
        }
}
