package ir.dicode.ping.core

import android.content.Context
import ir.dicode.ping.data.SettingsStore

/** Capability registry for signed cores bundled inside the APK. */
class AndroidCoreManager(private val context: Context) {
    enum class CapabilityState { installed, unsupportedInThisBuild, missingAuthorizedConfig }

    data class Capability(val coreId: String, val state: CapabilityState, val reason: String) {
        val canDownload: Boolean get() = false
        val canConnect: Boolean get() = state == CapabilityState.installed
    }

    private fun bundled(coreId: String): Boolean = when (coreId) {
        "aether", "warp" -> AndroidExternalCoreProcess(context, coreId).isBundled()
        "xray" -> true
        else -> false
    }

    fun capability(coreId: String): Capability = when (coreId) {
        "xray" -> Capability(coreId, CapabilityState.installed, "Xray is embedded in dicodePing.")
        "aether" -> if (bundled(coreId)) {
            Capability(coreId, CapabilityState.installed, "Aether is bundled for this device ABI.")
        } else Capability(coreId, CapabilityState.unsupportedInThisBuild, "Aether binary is missing for this ABI.")
        "warp" -> if (bundled(coreId)) {
            Capability(coreId, CapabilityState.installed, "Usque/WARP is bundled for this device ABI.")
        } else Capability(coreId, CapabilityState.unsupportedInThisBuild, "Usque binary is missing for this ABI.")
        "psiphon" -> Capability(
            coreId,
            CapabilityState.missingAuthorizedConfig,
            "Authorized Psiphon distribution configuration is unavailable in this build.",
        )
        else -> Capability(coreId, CapabilityState.unsupportedInThisBuild, "Unknown connection core.")
    }

    fun isInstalled(coreId: String): Boolean = capability(coreId).canConnect

    suspend fun initializeWarp() {
        AndroidExternalCoreProcess(context, "warp")
            .registerWarpIfNeeded(SettingsStore(context).warpTermsAccepted)
    }

    suspend fun install(
        coreId: String,
        @Suppress("UNUSED_PARAMETER") progress: (Long, Long) -> Unit = { _, _ -> },
    ) {
        check(isInstalled(coreId)) { capability(coreId).reason }
        if (coreId == "warp") initializeWarp()
    }
}
