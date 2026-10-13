package com.v2ray.ang.ui.server

import android.app.Application
import com.v2ray.ang.AppConfig.BUILTIN_OUTBOUND_TAGS
import com.v2ray.ang.AppConfig.TAG_PROXY
import com.v2ray.ang.core.CoreConfigContextBuilder
import com.v2ray.ang.enums.BalancerStrategyType
import com.v2ray.ang.enums.EConfigType
import com.v2ray.ang.ui.base.EditorOutcome
import kotlinx.coroutines.flow.StateFlow

/** PattNG: a subscription the policy group editor offers to draw members from: its [id], blank for all, and its [label]. */
data class PolicyGroupSubscription(val id: String, val label: String)

/**
 * PattNG: the subscriptions the policy group editor offers, [all] first, then [subscriptions], their keys beside their
 * names, under labels made unique, see [distinctLabels]: the list hands back the label picked, and two subscriptions
 * of the same name, or one named as [all] is, are two picks still.
 */
internal fun policyGroupSubscriptions(
    all: String,
    subscriptions: List<Pair<String, String>>,
    numbered: (String, Int) -> String,
): List<PolicyGroupSubscription> {
    val labels = distinctLabels(subscriptions.map { it.second }, setOf(all), numbered)
    return listOf(PolicyGroupSubscription("", all)) + subscriptions.mapIndexed { index, (id, _) -> PolicyGroupSubscription(id, labels[index]) }
}

/** PattNG: the subscription of these, as [policyGroupSubscriptions] offers them, whose key is [id]; all when none is, as for a subscription gone. */
internal fun List<PolicyGroupSubscription>.pick(id: String?): PolicyGroupSubscription = firstOrNull { it.id == id } ?: first()

/**
 * PattNG: what the policy group editor saves: its fields as the screen has them, the [type] and the [subscriptionId] as
 * picked, and the labels the screen shows for them, which make the group's description.
 */
data class PolicyGroupEdit(
    val remarks: String,
    val filter: String,
    val type: Int,
    val typeLabel: String,
    val subscriptionId: String?,
    val subscriptionLabel: String,
    val testOutbounds: Boolean,
    val fallbackTag: String,
)

/**
 * PattNG: what the policy group editor opens on: the group's fields as stored, as a new group has them otherwise, the
 * key of the subscription it draws from, [pickedSubscription], to pick among [subscriptions], their keys beside their
 * names, and the [fallbackSuggestions] it offers.
 */
data class PolicyGroupOpening(
    val remarks: String,
    val filter: String,
    val type: Int,
    val testOutbounds: Boolean,
    val fallbackTag: String,
    val pickedSubscription: String,
    val subscriptions: List<Pair<String, String>>,
    val fallbackSuggestions: List<String>,
)

/** PattNG: the save and the delete of the policy group editor, see [ProfileEditorViewModel]. */
class ServerGroupViewModel(
    application: Application,
    source: ProfileEditorSource,
    guid: String,
    subscriptionId: String?,
    serviceRunning: Boolean = false,
) : ProfileEditorViewModel(application, source, guid, subscriptionId, serviceRunning) {

    /**
     * What the screen opened on, read off the main thread, see [openedWith]. A group draws from the subscription it was
     * stored with; a new one from the subscription the screen was opened in, all when none.
     */
    val opened: StateFlow<PolicyGroupOpening?> = openedWith {
        val config = guid.takeIf { it.isNotEmpty() }?.let { source.loadProfile(it) }
        PolicyGroupOpening(
            remarks = config?.remarks ?: "",
            filter = config?.policyGroupFilter ?: "",
            type = config?.policyGroupType?.toIntOrNull() ?: 0,
            testOutbounds = config == null || config.policyGroupTestOutbounds != false ||
                !BalancerStrategyType.from(config.policyGroupType).supportsObservatory,
            fallbackTag = config?.policyGroupFallbackTag.orEmpty(),
            pickedSubscription = if (config != null) config.policyGroupSubscriptionId.orEmpty() else subscriptionId.orEmpty(),
            subscriptions = source.subscriptions(),
            fallbackSuggestions = (BUILTIN_OUTBOUND_TAGS + source.profileNames(setOf(EConfigType.CUSTOM, EConfigType.POLICYGROUP)))
                .filter { it != TAG_PROXY },
        )
    }

    /**
     * Saves the group as [edit] has it. The fallback of a group that tests its members names a profile, and the name has
     * to find that one profile, as at the start: a name no profile has, as after a rename or a delete, several have, or
     * only a group or a custom configuration has, is told rather than saved, see [CoreConfigContextBuilder.fallbackOf].
     */
    fun save(edit: PolicyGroupEdit) = launchSave {
        if (edit.remarks.isBlank()) return@launchSave null
        val fallback = edit.fallbackTag.trim().takeIf { it.isNotEmpty() }
        val fallsBack = BalancerStrategyType.from(edit.type.toString()).supportsObservatory && edit.testOutbounds
        if (fallsBack && fallback != null && fallback !in BUILTIN_OUTBOUND_TAGS) {
            val (_, problem) = CoreConfigContextBuilder.fallbackOf(fallback) { name, takes ->
                source.withProfileNames(takes) { find -> find(name) }
            }
            if (problem != null) return@launchSave EditorOutcome.Refused(problem.message, listOf(fallback))
        }

        store(EConfigType.POLICYGROUP) { config ->
            config.remarks = edit.remarks.trim()
            config.policyGroupFilter = edit.filter.trim()
            config.policyGroupType = edit.type.toString()
            config.policyGroupSubscriptionId = edit.subscriptionId
            config.policyGroupTestOutbounds = edit.testOutbounds
            config.policyGroupFallbackTag = fallback
            config.description = "${edit.typeLabel} - ${edit.subscriptionLabel} - ${config.policyGroupFilter}"
        }
    }
}
