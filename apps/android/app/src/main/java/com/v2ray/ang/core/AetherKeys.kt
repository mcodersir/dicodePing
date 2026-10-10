package com.v2ray.ang.core

import com.v2ray.ang.AppConfig
import com.v2ray.ang.dto.AetherEndpoint
import com.v2ray.ang.dto.AetherRange
import com.v2ray.ang.enums.AetherFingerprint
import com.v2ray.ang.enums.AetherKeyKind
import com.v2ray.ang.extension.nullIfBlank
import com.v2ray.ang.fmt.AetherFmt

/**
 * PattNG: the settings of the page that gets new WARP keys. They are that page's alone: no profile's settings reach
 * them, and they reach no profile. Text is kept as written and read when a run is built. [command] is blank unless it
 * was edited by hand, and then it runs as written, see [AetherKeys.isCustom].
 */
data class AetherKeysSettings(
    val kind: AetherKeyKind = AetherKeyKind.ALL,
    val enrollAddress: String = AppConfig.AETHER_ENROLL_ADDRESS,
    val fragment: Boolean = false,
    val fragmentSize: String = "",
    val fragmentDelay: String = "",
    val ech: Boolean = false,
    val echDns: String = AppConfig.AETHER_ECH_DNS,
    val echDomain: String = AppConfig.AETHER_ECH_DOMAIN,
    val fingerprint: AetherFingerprint = AetherFingerprint.CHROME,
    val exitNode: String = "",
    val finalMask: String = "",
    val dialMode: String = "",
    val command: String = "",
) {
    /**
     * The exit-node the run dials out through: the profile [exitNode] names by its name, see [AetherExit.node], or
     * else a plain one, with the finalMask and the dialMode set here.
     */
    val exit: AetherExit
        get() = exitNode.nullIfBlank()?.let { AetherExit(node = it.trim()) } ?: AetherExit(finalMask.nullIfBlank(), dialMode.nullIfBlank())
}

/**
 * PattNG: the run of the core that gets new WARP keys: its `--register`, which registers the keys asked for and
 * ends without scanning or opening a tunnel, with where the calls to the WARP API go, whether they hide their server
 * name with Encrypted Client Hello, and the cipher suites their TLS handshakes offer. See
 * [AetherIdentityManager.renew], which keeps the keys in use until the new ones are ready.
 */
object AetherKeys {

    /** The option that has the core register keys and end, with the word naming which. */
    private const val REGISTER = "--register"

    /** Why settings cannot run. */
    enum class Problem {
        INVALID_ENROLL_ADDRESS,
        INVALID_FRAGMENT,
        INVALID_ECH_DNS,
        INVALID_ECH_DOMAIN,
        INVALID_FINAL_MASK,
        INVALID_COMMAND,
    }

    /**
     * The arguments [settings] give: the keys to register first, the address the calls to the WARP API go to unless
     * it is left blank, the ClientHello of those calls in pieces when fragmenting is on (--fragment, which a run that
     * only registers keys applies to those calls alone), sized and spaced as set or as the core has them by default,
     * and whole without the flag, Encrypted Client Hello on those calls with the key of the ECH domain, asked of
     * the ECH DNS, and the TLS 1.2 cipher suites of the fingerprint, Chrome's as its rule, with GREASE left out where
     * the fingerprint has none.
     */
    fun arguments(settings: AetherKeysSettings): List<String> = buildList {
        addAll(listOf(REGISTER, settings.kind.register))
        settings.enrollAddress.trim().takeIf { it.isNotEmpty() }?.let { addAll(listOf("--api-address", it)) }
        if (settings.fragment) {
            add("--fragment")
            AetherRange.parse(settings.fragmentSize, AetherRange.FRAGMENT_SIZE)?.let { addAll(listOf("--fragment-size", it.toString())) }
            AetherRange.parse(settings.fragmentDelay, AetherRange.FRAGMENT_DELAY)?.let { addAll(listOf("--fragment-delay", it.toString())) }
        }
        if (settings.ech) {
            addAll(listOf("--ech", "auto"))
            addAll(listOf("--ech-dns", settings.echDns.trim().ifEmpty { AppConfig.AETHER_ECH_DNS }))
            addAll(listOf("--ech-domain", settings.echDomain.trim().ifEmpty { AppConfig.AETHER_ECH_DOMAIN }))
        }
        addAll(settings.fingerprint.arguments)
    }

    /** The command line [arguments] makes of [settings], as the page shows it. */
    fun builtCommand(settings: AetherKeysSettings): String = AetherCore(arguments(settings)).command

    /** Whether [settings] carry a command written by hand: one that is not blank and not the one the settings give. */
    fun isCustom(settings: AetherKeysSettings): Boolean =
        settings.command.isNotBlank() && settings.command.trim() != builtCommand(settings)

    /** The arguments a run of [settings] starts the core with: those of the command written by hand, or the settings'. */
    fun runArguments(settings: AetherKeysSettings): List<String> =
        if (isCustom(settings)) AetherCore.argumentsOf(settings.command) else arguments(settings)

    /** The keys [arguments] register, read as the core reads them: the word after the last --register; null without one it takes. */
    fun kindOf(arguments: List<String>): AetherKeyKind? =
        arguments.lastIndexOf(REGISTER).takeIf { it >= 0 }?.let { AetherKeyKind.ofRegister(arguments.getOrNull(it + 1)) }

    /**
     * Why [settings] cannot run, or null when they can. A command written by hand is only checked for what it
     * registers: the settings it replaces do not count, and the core names what else it does not take. The
     * finalMask counts either way, since the run dials out through it, and is checked as well while a profile is
     * the exit-node, which leaves it out of use, as the Aether page checks it: no broken one is kept for freedom.
     * Whether one profile, and one only, has that name still is for the run to look up.
     */
    fun problem(settings: AetherKeysSettings): Problem? {
        if (!AetherExit.takesFinalMask(settings.finalMask)) return Problem.INVALID_FINAL_MASK
        if (isCustom(settings)) return Problem.INVALID_COMMAND.takeIf { kindOf(runArguments(settings)) == null }
        val address = settings.enrollAddress.trim()
        if (address.isNotEmpty() && !isEnrollAddress(address)) return Problem.INVALID_ENROLL_ADDRESS
        if (settings.fragment && !(takesRange(settings.fragmentSize, AetherRange.FRAGMENT_SIZE) && takesRange(settings.fragmentDelay, AetherRange.FRAGMENT_DELAY))) {
            return Problem.INVALID_FRAGMENT
        }
        if (settings.ech) {
            val dns = settings.echDns.trim()
            if (dns.isNotEmpty() && !AetherFmt.isEchDns(dns)) return Problem.INVALID_ECH_DNS
            val domain = settings.echDomain.trim()
            if (domain.isNotEmpty() && !AetherFmt.isEchDomain(domain)) return Problem.INVALID_ECH_DOMAIN
        }
        return null
    }

    /**
     * Whether [value] is an address the core sends the calls to the WARP API to, as its --api-address takes it: an
     * IP address, an IPv6 one with or without brackets, or a domain name, alone or followed by :port, an IPv6 address
     * then in brackets. A label of the name cannot start or end with '-', so that no value reads as an option.
     */
    internal fun isEnrollAddress(value: String): Boolean {
        if (isEnrollHost(value)) return true
        val separator = value.lastIndexOf(':')
        if (separator <= 0) return false
        val host = value.substring(0, separator)
        if (':' in host && !(host.startsWith('[') && host.endsWith(']'))) return false
        val port = value.substring(separator + 1)
        return port.length in 1..5 && port.all { it in '0'..'9' } && port.toInt() in 1..65535 && isEnrollHost(host)
    }

    /** Whether [text] is blank, the core's own default, or a number or range within [bounds]. */
    private fun takesRange(text: String, bounds: IntRange): Boolean = text.isBlank() || AetherRange.parse(text, bounds) != null

    /** An IP address, an IPv6 one with or without brackets, or a domain name. */
    private fun isEnrollHost(host: String): Boolean = AetherEndpoint.of(host, "443") != null || AetherFmt.isEchDomain(host)
}
