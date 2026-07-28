package ir.dicode.ping.core

import android.content.Context
import ir.dicode.ping.R
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
        "xray" -> Capability(coreId, CapabilityState.installed, context.getString(R.string.core_xray_builtin))
        "aether" -> if (bundled(coreId)) {
            Capability(coreId, CapabilityState.installed, context.getString(R.string.core_aether_bundled))
        } else Capability(coreId, CapabilityState.unsupportedInThisBuild, context.getString(R.string.core_aether_missing))
        "warp" -> if (bundled(coreId)) {
            Capability(coreId, CapabilityState.installed, context.getString(R.string.core_warp_bundled))
        } else Capability(coreId, CapabilityState.unsupportedInThisBuild, context.getString(R.string.core_warp_missing))
        "psiphon" -> Capability(
            coreId,
            CapabilityState.missingAuthorizedConfig,
            context.getString(R.string.core_psiphon_authorization_missing),
        )
        else -> Capability(coreId, CapabilityState.unsupportedInThisBuild, context.getString(R.string.core_unknown))
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
