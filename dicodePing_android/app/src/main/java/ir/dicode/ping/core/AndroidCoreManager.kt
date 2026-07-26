package ir.dicode.ping.core

import android.content.Context

/**
 * Capability registry for connection cores shipped in this Android build.
 *
 * RC3 intentionally enables only the embedded libv2ray transport. Optional
 * desktop executables are never downloaded or launched on Android. Future
 * transports must be same-package libraries signed with the application.
 */
class AndroidCoreManager(@Suppress("UNUSED_PARAMETER") context: Context) {
    enum class CapabilityState {
        installed,
        unsupportedInThisBuild,
        missingAuthorizedConfig,
    }

    data class Capability(
        val coreId: String,
        val state: CapabilityState,
        val reason: String,
    ) {
        val canDownload: Boolean get() = false
        val canConnect: Boolean get() = state == CapabilityState.installed
    }

    fun capability(coreId: String): Capability = when (coreId) {
        "xray" -> Capability(
            coreId,
            CapabilityState.installed,
            "Xray is built into dicodePing and is the scanner transport.",
        )
        "psiphon" -> Capability(
            coreId,
            CapabilityState.missingAuthorizedConfig,
            "Authorized Psiphon distribution configuration is unavailable in this build.",
        )
        "aether" -> Capability(
            coreId,
            CapabilityState.unsupportedInThisBuild,
            "A same-package Aether library is not included in this Android build.",
        )
        "warp" -> Capability(
            coreId,
            CapabilityState.unsupportedInThisBuild,
            "A same-package Usque library is not included in this Android build.",
        )
        else -> Capability(
            coreId,
            CapabilityState.unsupportedInThisBuild,
            "Unknown connection core.",
        )
    }

    fun isInstalled(coreId: String): Boolean = capability(coreId).canConnect

    suspend fun install(
        coreId: String,
        @Suppress("UNUSED_PARAMETER") progress: (Long, Long) -> Unit = { _, _ -> },
    ): Nothing {
        // No Android executable install path: no "SHA-256 mismatch" flow and
        // no File.renameTo(target); unsupported transports stay disabled.
        error(capability(coreId).reason)
    }
}
