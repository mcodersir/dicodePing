package com.v2ray.ang.ui.server

import android.app.Application
import androidx.lifecycle.viewModelScope
import com.v2ray.ang.R
import com.v2ray.ang.dto.entities.ProfileItem
import com.v2ray.ang.enums.EConfigType
import com.v2ray.ang.ui.base.EditorOutcome
import com.v2ray.ang.ui.base.EditorViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * PattNG: the save and the delete of the editor of a profile, see [EditorViewModel]: one made of other profiles, a
 * proxy chain or a policy group, one the screen builds whole, see [ServerEditorViewModel], or a custom one. The profile
 * is stored as [guid]: the one the screen was opened on, or, for a new one, a guid of its own got before its first write,
 * so that a later save writes over what that one stored, even part of it, when the storage refused the rest. A new one
 * goes into the subscription [subscriptionId], when the screen was opened in one.
 */
abstract class ProfileEditorViewModel(
    application: Application,
    protected val source: ProfileEditorSource,
    guid: String,
    private val subscriptionId: String?,
    serviceRunning: Boolean = false,
) : EditorViewModel(application) {

    private val _isRunning = MutableStateFlow(if (serviceRunning && guid.isNotEmpty()) null else false)

    /**
     * Whether the app runs on the profile the screen was opened on, [serviceRunning] as it was told and the profile the one
     * selected, read off the main thread; null until read. The screen offers no delete of it, and a save restarts it.
     */
    val isRunning: StateFlow<Boolean?> = _isRunning.asStateFlow()

    init {
        if (_isRunning.value == null) viewModelScope.launch { _isRunning.value = source.isSelected(guid) }
    }

    /** The guid the profile is stored as, see the class; blank for a new one until its first save. */
    protected var guid: String = guid
        private set

    /** The guid the next write stores the profile as, see the class: a new one gets its own here, kept from now on. */
    private fun storedAs(): String = guid.ifEmpty { source.newGuid().also { guid = it } }

    /**
     * Stores the profile, of [type], with [edit] made on it, and [raw] with it when given, see
     * [ProfileEditorSource.saveProfile], and keeps the guid it is stored as; a write the storage refused is told, see
     * [WRITE_REFUSED].
     */
    protected suspend fun store(type: EConfigType, raw: String? = null, edit: (ProfileItem) -> Unit): EditorOutcome {
        guid = source.saveProfile(storedAs(), type, raw) { config ->
            edit(config)
            stampSubscription(config)
        } ?: return WRITE_REFUSED
        return EditorOutcome.Saved(guid)
    }

    /**
     * Stores [profile], which the screen built whole, see [ProfileEditorSource.storeProfile], and keeps the guid it is
     * stored as; a write the storage refused is told, see [WRITE_REFUSED].
     */
    protected suspend fun store(profile: ProfileItem): EditorOutcome {
        stampSubscription(profile)
        guid = source.storeProfile(storedAs(), profile) ?: return WRITE_REFUSED
        return EditorOutcome.Saved(guid)
    }

    private fun stampSubscription(config: ProfileItem) {
        if (config.subscriptionId.isEmpty() && !subscriptionId.isNullOrEmpty()) {
            config.subscriptionId = subscriptionId
        }
    }

    private companion object {
        /** A write or a delete the storage refused, as when the device is full: told, and the screen stays open for another try. */
        val WRITE_REFUSED = EditorOutcome.Refused(R.string.toast_failure)
    }

    /**
     * Deletes the profile, off the main thread, once a save that runs has ended, unless it is the profile the app runs on,
     * which is told rather than deleted; see [EditorViewModel.launchDelete]. A delete the storage refused is told, see
     * [WRITE_REFUSED]. A new one, never saved, has none to delete.
     */
    fun delete() {
        val stored = guid.takeIf { it.isNotEmpty() } ?: return
        launchDelete(
            refuse = { EditorOutcome.Refused(R.string.toast_action_not_allowed).takeIf { source.isSelected(stored) } },
            delete = { WRITE_REFUSED.takeUnless { source.deleteProfile(stored) } },
        )
    }
}
