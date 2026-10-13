package com.v2ray.ang.ui.server

import androidx.annotation.StringRes
import com.v2ray.ang.core.CoreConfigContextBuilder
import com.v2ray.ang.dto.ByName
import com.v2ray.ang.dto.entities.ProfileItem
import com.v2ray.ang.enums.EConfigType

/** Removes one draft member and its row key together, resolving its current position at confirmation. */
internal fun withoutProxyChainMember(
    members: List<String>,
    memberKeys: List<String>,
    memberKey: String,
): Pair<List<String>, List<String>> {
    val index = memberKeys.indexOf(memberKey)
    if (index < 0) return members to memberKeys

    return members.toMutableList().also { it.removeAt(index) } to
        memberKeys.toMutableList().also { it.removeAt(index) }
}

/**
 * True when [memberTypes], the types of a chain's members, hold more than one Aether profile. One can
 * stand anywhere in the chain; a second would need a core of its own, and one core runs at a time.
 */
internal fun hasSecondAetherMember(memberTypes: List<EConfigType?>): Boolean =
    memberTypes.count { it == EConfigType.AETHER } > 1

/** PattNG: why a proxy chain cannot be saved with its members, see [proxyChainProblem]. */
internal sealed interface ProxyChainProblem {
    /**
     * The member [name] cannot be a hop, for the [message] that tells why, whose argument is the name: no profile that
     * can be a hop has it, or none any more, several have it, the one that has it has no server address, or only a
     * group, a chain or a custom configuration has it.
     */
    data class Unresolved(val name: String, @StringRes val message: Int) : ProxyChainProblem

    /** A second Aether member, see [hasSecondAetherMember]. */
    data object SecondAether : ProxyChainProblem
}

/**
 * PattNG: why a chain of [members], the names of its profiles in its order, cannot be saved, as the chain finds its
 * hops when it runs, see [CoreConfigContextBuilder.proxyChainHops]: the first of the names that finds no profile that
 * can be a hop, several, one without a server address, or only a group, a chain or a custom configuration, or a
 * second Aether member. Null when it can. [find] looks a name up among the profiles a filter takes, see [ByName];
 * inline, so that an editor looks up through its own source, which suspends. The previous and the next profile of a
 * subscription, which chain each of its profiles, are checked alike, in the order the chain finds them.
 */
internal inline fun proxyChainProblem(members: List<String>, find: (String, (ProfileItem) -> Boolean) -> ByName<ProfileItem>): ProxyChainProblem? {
    val (hops, unresolved) = CoreConfigContextBuilder.proxyChainHops(members, find)
    unresolved?.let { return ProxyChainProblem.Unresolved(it.name, it.reason.message) }
    return ProxyChainProblem.SecondAether.takeIf { hasSecondAetherMember(hops.map { it.configType }) }
}
