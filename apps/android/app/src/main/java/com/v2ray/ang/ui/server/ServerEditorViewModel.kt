package com.v2ray.ang.ui.server

import android.app.Application
import com.v2ray.ang.dto.entities.ProfileItem
import com.v2ray.ang.enums.EConfigType
import kotlinx.coroutines.flow.StateFlow

/**
 * PattNG: the save and the delete of the editor of a profile the screen builds whole from what it shows, as a VLESS or
 * an Aether one, see [BaseServerActivity] and [ProfileEditorViewModel]: unlike a proxy chain's, whose screen sets a few
 * fields on the profile as stored, the profile is stored as built.
 */
class ServerEditorViewModel(
    application: Application,
    source: ProfileEditorSource,
    guid: String,
    subscriptionId: String?,
    type: EConfigType,
    serviceRunning: Boolean = false,
) : ProfileEditorViewModel(application, source, guid, subscriptionId, serviceRunning) {

    /**
     * The profile the screen opened on, read off the main thread, see [openedWith]: the one [guid] names, or a new one
     * of [type], as for a new profile, or one gone by then.
     */
    val opened: StateFlow<ProfileItem?> = openedWith {
        guid.takeIf { it.isNotEmpty() }?.let { source.loadProfile(it) } ?: ProfileItem.create(type)
    }

    /** Stores [profile], which the screen has built and checked, off the main thread. */
    fun save(profile: ProfileItem) = launchSave { store(profile) }
}
