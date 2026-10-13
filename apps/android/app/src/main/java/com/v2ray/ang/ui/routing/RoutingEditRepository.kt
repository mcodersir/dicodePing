package com.v2ray.ang.ui.routing

import com.v2ray.ang.AppConfig
import com.v2ray.ang.dto.ByName
import com.v2ray.ang.dto.entities.ProfileItem
import com.v2ray.ang.dto.entities.RulesetItem
import com.v2ray.ang.enums.EConfigType
import com.v2ray.ang.handler.MmkvManager
import com.v2ray.ang.extension.moveItem
import com.v2ray.ang.handler.SettingsManager
import com.v2ray.ang.ui.server.ProfileNameSource
import com.v2ray.ang.ui.server.storedProfileNames
import com.v2ray.ang.ui.server.withStoredProfileNames
import com.v2ray.ang.util.LogUtil
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * PattNG: where the routing rule editor reads what it opens on, finds the profile a rule sends to and stores, or
 * deletes, the rule.
 */
interface RoutingEditSource : ProfileNameSource {
    /** The rule the editor opens on, read off the main thread, see [openedRule]. */
    suspend fun loadRule(position: Int, reopenedId: String?): RulesetItem?

    /** The names of the stored profiles but custom ones, read off the main thread, see [storedProfileNames]. */
    suspend fun profileNames(): List<String>

    /** Whether a rule can match the app a connection comes from, see [SettingsManager.canUseProcessRouting], read off the main thread. */
    suspend fun canUseProcessRouting(): Boolean

    /**
     * Stores [rule] where the rule of its id is stored now, see [storedAt]; first when no rule has the id any more, or
     * when the rule is new, as [SettingsManager.saveRoutingRuleset] does. [position] is where the screen was opened on it.
     * False, logged, when the storage refused it.
     */
    suspend fun saveRule(position: Int, rule: RulesetItem): Boolean

    /**
     * Deletes the rule of [id] where it is stored now, see [storedAt]; nothing when no rule has the id any more. False,
     * logged, when the storage refused it.
     */
    suspend fun deleteRule(position: Int, id: String): Boolean
}

/**
 * PattNG: where the routing settings screen reads its rules and stores what it changes in their list, whether each is
 * on and their order, see [RoutingSettingsViewModel], by the ids of the rules.
 */
interface RoutingSettingsSource {
    /**
     * The stored rules with an id of their own each, see [SettingsManager.rulesetsWithOwnIds]: put right, and stored so,
     * when they were not.
     */
    suspend fun loadRules(): List<RulesetItem>

    /** Stores [rule] in place of the stored rule with its id; nothing when no rule has it any more. */
    suspend fun updateRule(rule: RulesetItem)

    /** Moves the stored rule of [fromId] to where the rule of [toId] stands; nothing when no rule has either any more. */
    suspend fun moveRule(fromId: String, toId: String)
}

/**
 * PattNG: where the rule of [id] stands among [rules] now, found again by its id, since the list may have changed while
 * the editor was open: -1 when no rule has it. A rule from before rules had ids goes by [position], where the screen was
 * opened on it, while the list reaches that far.
 */
internal fun storedAt(rules: List<RulesetItem>?, id: String, position: Int): Int {
    val list = rules.orEmpty()
    return if (id.isNotEmpty()) list.indexOfFirst { it.id == id } else position.takeIf { it in list.indices } ?: -1
}

/**
 * PattNG: the rule an editor opens on among [rules]: the one of [reopenedId], the id the editor kept, when it comes back
 * after its process was gone, else the one at [position]; null for none, as for a new rule or one gone.
 */
internal fun openedRule(rules: List<RulesetItem>?, position: Int, reopenedId: String?): RulesetItem? =
    if (reopenedId != null) rules?.firstOrNull { it.id == reopenedId } else rules?.getOrNull(position)

/**
 * PattNG: [RoutingEditSource] and [RoutingSettingsSource] over [MmkvManager], which stores the routing rules: it moves
 * their reads and writes off the main thread, each read, change and write while no other runs, see
 * [SettingsManager.changeRoutingRulesets], finding a rule again by its id, logs a write the storage refused, and lets
 * the screens' view models be tested without it.
 */
class RoutingEditRepository : RoutingEditSource, RoutingSettingsSource {

    override suspend fun <T> withProfileNames(takes: (ProfileItem) -> Boolean, check: (find: (String) -> ByName<ProfileItem>) -> T): T =
        withStoredProfileNames(takes, check)

    override suspend fun loadRule(position: Int, reopenedId: String?): RulesetItem? =
        withContext(Dispatchers.IO) { openedRule(MmkvManager.decodeRoutingRulesets(), position, reopenedId) }

    override suspend fun profileNames(): List<String> = storedProfileNames(setOf(EConfigType.CUSTOM))

    override suspend fun canUseProcessRouting(): Boolean = withContext(Dispatchers.IO) { SettingsManager.canUseProcessRouting() }

    // One read and one write each, as SettingsManager.saveRoutingRuleset and removeRoutingRuleset make them, so that the
    // rule found is the rule written however the list changes meanwhile.
    override suspend fun saveRule(position: Int, rule: RulesetItem): Boolean = change("rule ${rule.id}") {
        val rules = MmkvManager.decodeRoutingRulesets() ?: mutableListOf()
        when (val index = storedAt(rules, rule.id, position)) {
            -1 -> rules.add(0, rule)
            else -> rules[index] = rule
        }
        MmkvManager.encodeRoutingRulesets(rules)
    }

    override suspend fun deleteRule(position: Int, id: String): Boolean = change("the list without rule $id") {
        val rules = MmkvManager.decodeRoutingRulesets() ?: return@change true
        val index = storedAt(rules, id, position).takeIf { it >= 0 } ?: return@change true
        rules.removeAt(index)
        MmkvManager.encodeRoutingRulesets(rules)
    }

    override suspend fun loadRules(): List<RulesetItem> = withContext(Dispatchers.IO) {
        SettingsManager.changeRoutingRulesets {
            val stored = MmkvManager.decodeRoutingRulesets().orEmpty()
            val ownIds = SettingsManager.rulesetsWithOwnIds(stored) ?: return@changeRoutingRulesets stored
            // Shown so even when the storage refuses them, which a list keyed by the ids could not be otherwise.
            written(MmkvManager.encodeRoutingRulesets(ownIds), "the rules with ids of their own")
            ownIds
        }
    }

    override suspend fun updateRule(rule: RulesetItem) {
        change("rule ${rule.id}") {
            val rules = MmkvManager.decodeRoutingRulesets() ?: return@change true
            val index = rules.indexOfFirst { it.id == rule.id }.takeIf { it >= 0 } ?: return@change true
            rules[index] = rule
            MmkvManager.encodeRoutingRulesets(rules)
        }
    }

    override suspend fun moveRule(fromId: String, toId: String) {
        change("the order of the rules") {
            val rules = MmkvManager.decodeRoutingRulesets() ?: return@change true
            !rules.moveItem(rules.indexOfFirst { it.id == fromId }, rules.indexOfFirst { it.id == toId }) ||
                MmkvManager.encodeRoutingRulesets(rules)
        }
    }

    /** What [write], a read, change and write of the stored rules, gives, off the main thread, a refusal logged as of [what]. */
    private suspend fun change(what: String, write: () -> Boolean): Boolean = withContext(Dispatchers.IO) {
        written(SettingsManager.changeRoutingRulesets(write), what)
    }

    private fun written(taken: Boolean, what: String): Boolean {
        if (!taken) LogUtil.e(AppConfig.TAG, "Routing rules: the storage refused $what")
        return taken
    }
}
