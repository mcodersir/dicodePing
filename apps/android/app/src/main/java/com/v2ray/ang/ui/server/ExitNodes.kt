package com.v2ray.ang.ui.server

import com.v2ray.ang.core.AetherExitNode
import com.v2ray.ang.core.ExitNodeOutbound

/**
 * The labels a pick list shows for [names], in their order, as the exit-node lists and the subscriptions of the policy
 * group editor show theirs: each name, made unique by a number after it, which [numbered] writes, where it is one of
 * [reserved], the labels of the list's own entries, or came up before. The list hands back the label picked, so no two
 * may be alike.
 */
internal fun distinctLabels(names: List<String>, reserved: Set<String>, numbered: (String, Int) -> String): List<String> {
    val taken = reserved.toMutableSet()
    return names.map { name ->
        var label = name
        var number = 2
        while (label in taken) label = numbered(name, number++)
        taken += label
        label
    }
}

/**
 * Why the exit-node named [name] cannot be used, as far as [nodes], the names of the profiles that can be one, tell:
 * no profile has the name any more, or several have it. Null when one has it, when no name is set, and until the
 * nodes are read.
 */
internal fun problemOfExitNode(name: String, nodes: List<AetherExitNode>?): ExitNodeOutbound.Problem? {
    val wanted = name.trim()
    if (wanted.isEmpty() || nodes == null) return null
    val profiles = nodes.firstOrNull { it.name == wanted }?.profiles ?: 0
    return when {
        profiles == 0 -> ExitNodeOutbound.NotFound
        profiles > 1 -> ExitNodeOutbound.SameName
        else -> null
    }
}
