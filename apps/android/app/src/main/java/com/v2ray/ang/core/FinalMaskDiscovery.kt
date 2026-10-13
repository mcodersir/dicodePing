package com.v2ray.ang.core

import android.content.Context
import com.v2ray.ang.dto.entities.ProfileItem
import com.v2ray.ang.handler.MmkvManager
import com.v2ray.ang.service.RealPingProbe
import com.v2ray.ang.util.JsonUtil
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.CancellationException
import java.util.UUID

/** Temporary profiles are always removed; only a twice-validated winner changes the selected profile. */
object FinalMaskDiscovery {
    suspend fun discover(context: Context, guid: String, progress: (String) -> Unit): Long = withTimeout(90_000) {
        val original = MmkvManager.decodeServerConfig(guid) ?: error("Profile no longer exists")
        require(TlsSettingsCheck.appliesTo(original)) { "Select an individual TLS profile" }
        val serialized = JsonUtil.toJson(original)
        val preset = original.copy().also { TlsSettingsCheck.applySniPreset(it) }.finalMask.orEmpty()
        val masks = listOf(original.finalMask.orEmpty(), preset,
            preset.replace("[\"6\",\"98\",\"1\"]", "[\"10-30\"]").replace("[\"0\"]", "[\"1-3\"]")).distinct()
        val results = mutableListOf<Pair<String, Long>>()
        for ((index, mask) in masks.withIndex()) {
            currentCoroutineContext().ensureActive()
            progress("${index + 1} / ${masks.size}")
            val tempGuid = UUID.randomUUID().toString()
            try {
                MmkvManager.encodeServerConfig(tempGuid, original.copy(finalMask = mask))
                withTimeout(25_000) {
                    val first = RealPingProbe.measure(context, tempGuid)
                    val second = RealPingProbe.measure(context, tempGuid)
                    if (first > 0 && second > 0) results += mask to ((first + second) / 2)
                }
            } catch (cancelled: CancellationException) {
                currentCoroutineContext().ensureActive()
            } catch (error: Exception) {
                com.v2ray.ang.util.LogUtil.e(com.v2ray.ang.AppConfig.TAG, "FinalMask candidate failed", error)
            } finally { check(MmkvManager.tryRemoveServer(tempGuid)) { "Could not remove temporary probe profile" } }
        }
        val winner = results.minByOrNull { it.second } ?: error("No candidate passed real traffic tests")
        val current = MmkvManager.decodeServerConfig(guid) ?: error("Profile no longer exists")
        check(JsonUtil.toJson(current) == serialized) { "Profile changed during discovery" }
        MmkvManager.encodeServerConfig(guid, current.copy(finalMask = winner.first))
        winner.second
    }
}
