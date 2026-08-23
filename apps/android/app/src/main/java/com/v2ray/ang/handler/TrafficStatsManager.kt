package com.v2ray.ang.handler

import com.tencent.mmkv.MMKV
import com.v2ray.ang.util.JsonUtil
import java.time.LocalDate

data class DailyTraffic(val upload: Long = 0, val download: Long = 0)

object TrafficStatsManager {
    private const val STORAGE_ID = "TRAFFIC_DAILY"
    private val storage by lazy { MMKV.mmkvWithID(STORAGE_ID, MMKV.MULTI_PROCESS_MODE) }

    @Synchronized
    fun record(profileId: String?, upload: Long, download: Long) {
        if (profileId.isNullOrBlank() || upload + download <= 0) return
        val key = "${LocalDate.now()}::$profileId"
        val current = read(key)
        storage.encode(key, JsonUtil.toJson(DailyTraffic(current.upload + upload, current.download + download)))
        prune()
    }

    fun today(profileId: String?): DailyTraffic =
        if (profileId.isNullOrBlank()) DailyTraffic() else read("${LocalDate.now()}::$profileId")

    fun todayAll(): List<Pair<String, DailyTraffic>> {
        val prefix = "${LocalDate.now()}::"
        return storage.allKeys()?.filter { it.startsWith(prefix) }
            ?.map { it.removePrefix(prefix) to read(it) }
            ?.sortedByDescending { it.second.upload + it.second.download }
            .orEmpty()
    }

    private fun read(key: String): DailyTraffic =
        JsonUtil.fromJsonSafe(storage.decodeString(key).orEmpty(), DailyTraffic::class.java) ?: DailyTraffic()

    private fun prune() {
        val cutoff = LocalDate.now().minusDays(31)
        storage.allKeys()?.forEach { key ->
            val date = runCatching { LocalDate.parse(key.substringBefore("::")) }.getOrNull()
            if (date != null && date.isBefore(cutoff)) storage.removeValueForKey(key)
        }
    }
}
