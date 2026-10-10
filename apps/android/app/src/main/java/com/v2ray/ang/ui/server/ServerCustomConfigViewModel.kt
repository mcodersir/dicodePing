package com.v2ray.ang.ui.server

import android.app.Application
import com.v2ray.ang.R
import com.v2ray.ang.enums.EConfigType
import com.v2ray.ang.handler.AngConfigManager
import com.v2ray.ang.ui.base.EditorOutcome
import kotlinx.coroutines.flow.StateFlow

/** PattNG: what the custom configuration editor opens on: the profile's [remarks] and its configuration in full, [content]. */
data class CustomConfigOpening(val remarks: String, val content: String)

/**
 * PattNG: the save and the delete of the custom configuration editor, see [ProfileEditorViewModel]. The screen edits a
 * custom profile it was opened on, and leaves it in the subscription it is in.
 */
class ServerCustomConfigViewModel(
    application: Application,
    source: ProfileEditorSource,
    guid: String,
    serviceRunning: Boolean = false,
) : ProfileEditorViewModel(application, source, guid, subscriptionId = null, serviceRunning = serviceRunning) {

    /** What the screen opened on, read off the main thread, see [openedWith]. */
    val opened: StateFlow<CustomConfigOpening?> = openedWith {
        CustomConfigOpening(source.loadProfile(guid)?.remarks.orEmpty(), source.loadRaw(guid).orEmpty())
    }

    /**
     * Saves the configuration [content] with its profile, named [remarks], which gets the server and the port the
     * configuration describes, as stored then; read off the main thread. One that cannot be read is told, see
     * [malformedConfig], rather than saved.
     */
    fun save(remarks: String, content: String) = launchSave {
        if (remarks.isBlank()) return@launchSave null
        val parsed = source.parseCustomConfig(guid, content).getOrElse { return@launchSave malformedConfig(it) }
        store(EConfigType.CUSTOM, raw = content) { config ->
            config.remarks = remarks
            config.server = parsed.server
            config.serverPort = parsed.serverPort
            config.description = AngConfigManager.generateDescription(config)
        }
    }
}

/** PattNG: the refusal of a custom configuration whose reading ended with [failure]: with what it says, when it says something. */
internal fun malformedConfig(failure: Throwable): EditorOutcome.Refused {
    val detail = failure.cause?.message?.takeIf { it.isNotBlank() }
        ?: failure.message?.takeIf { it.isNotBlank() }
    return if (detail == null) {
        EditorOutcome.Refused(R.string.toast_malformed_json)
    } else {
        EditorOutcome.Refused(R.string.toast_malformed_json_detail, listOf(detail))
    }
}
