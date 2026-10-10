package com.v2ray.ang.core

import android.content.Context
import android.net.ConnectivityManager
import com.v2ray.ang.AppConfig
import com.v2ray.ang.dto.entities.ProfileItem
import com.v2ray.ang.enums.*
import com.v2ray.ang.handler.MmkvManager
import com.v2ray.ang.service.RealPingProbe
import com.v2ray.ang.util.JsonUtil
import kotlinx.coroutines.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.security.MessageDigest
import java.util.UUID

/** Uses the packaged helper's supported modes; readiness always means traffic through its SOCKS endpoint. */
object AetherTransportDiscovery {
    private val gate = Mutex()
    private fun networkKey(context: Context): String {
        val manager = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val network = manager.activeNetwork
        val signature = manager.getLinkProperties(network).toString() + manager.getNetworkCapabilities(network).toString()
        return MessageDigest.getInstance("SHA-256").digest(signature.toByteArray()).joinToString("") { "%02x".format(it) }
    }
    suspend fun prepare(context: Context, guid: String, rescan: Boolean = false, progress: (String) -> Unit = {}): Long = gate.withLock {
        val original = MmkvManager.decodeServerConfig(guid) ?: error("Profile no longer exists")
        require(original.configType == EConfigType.AETHER) { "Select an Aether/Psiphon profile to scan" }
        require(original.aetherCommand.isNullOrBlank()) { "Custom Aether commands are preserved; automatic discovery requires a settings-based profile" }
        check(AetherCoreManager.isSupported(context)) { "Aether is unavailable for this architecture" }
        val key = networkKey(context)
        if (!rescan && original.aetherDiscoveryNetwork == key) return@withLock 0L
        val identity = JsonUtil.toJson(original)
        val onlyPsiphon = AetherPsiphon.fromString(original.aetherPsiphon) == AetherPsiphon.ONLY
        val reverse = AetherPsiphon.fromString(original.aetherPsiphon) == AetherPsiphon.REVERSE || AetherTor.fromString(original.aetherTor) == AetherTor.REVERSE
        val candidates = if (onlyPsiphon) listOf(original.copy()) else buildList {
            for (protocol in AetherProtocol.entries) {
                if (reverse && !protocol.overMasque) continue
                val transports = if (protocol.overMasque && !reverse) AetherTransport.entries else listOf(AetherTransport.HTTP2)
                for (transport in transports) add(original.copy(aetherProtocol = protocol.type, aetherTransport = transport.type, aetherScanMode = "turbo", server = null))
            }
        }
        val best = MmkvManager.decodeSettingsBool(AppConfig.PREF_DICODE_AETHER_BEST, false)
        withTimeout(150_000) {
            val successes = mutableListOf<Pair<ProfileItem, Long>>()
            for ((index, candidate) in candidates.withIndex()) {
                currentCoroutineContext().ensureActive()
                progress("Aether · ${index + 1} / ${candidates.size}")
                val temp = UUID.randomUUID().toString()
                try {
                    MmkvManager.encodeServerConfig(temp, candidate)
                    val delay = withTimeout(18_000) { RealPingProbe.measure(context, temp) }
                    if (delay > 0) { successes += candidate to delay; if (!best) break }
                } catch (cancelled: CancellationException) { currentCoroutineContext().ensureActive() }
                catch (error: Exception) { com.v2ray.ang.util.LogUtil.e(AppConfig.TAG, "Aether transport candidate failed", error) }
                finally { check(MmkvManager.tryRemoveServer(temp)) { "Could not remove temporary transport profile" } }
            }
            val winner = successes.minByOrNull { it.second } ?: error("No Aether/Psiphon transport passed real traffic tests")
            val current = MmkvManager.decodeServerConfig(guid) ?: error("Profile no longer exists")
            check(JsonUtil.toJson(current) == identity) { "Profile changed during discovery" }
            MmkvManager.encodeServerConfig(guid, winner.first.copy(aetherDiscoveryNetwork = key))
            winner.second
        }
    }
}
