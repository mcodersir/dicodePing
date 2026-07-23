package ir.dicode.ping.net

import ir.dicode.ping.data.ServerRecord

/**
 * Volume-based config detection (beta) — mirrors the desktop ``volume.py``.
 *
 * Many free/server-side limited configs embed traffic or time quotas in
 * their remark name (the part after ``#`` in the URI).  We use a small
 * set of regex patterns to extract those numbers and present them next
 * to the ping in the server list.
 *
 * The detection is intentionally best-effort and labelled beta.  Many
 * providers do not embed the quota in the remark, in which case we show
 * "—".
 *
 * Per the user's request, when a server is detected as volume-limited
 * and the user connects to it, the VPN service arms an auto-disconnect
 * timer (default one hour) so the user does not have to remember to
 * disconnect manually.
 */
object VolumeDetector {
    private val GB_PATTERN = Regex("(?i)\\b(\\d+(?:[.,]\\d+)?)\\s*(gb|gig|g)\\b(?!\\s*hz)")
    private val MB_PATTERN = Regex("(?i)\\b(\\d+(?:[.,]\\d+)?)\\s*(mb|meg|m)\\b(?!\\s*hz)")
    private val TIME_PATTERN = Regex("(?i)\\b(\\d+)\\s*(d|day|days|h|hr|hour|hours|w|week|weeks)\\b")
    private val LIMIT_KEYWORDS = Regex("(?i)(volume|vol|limit|data|gb|mb|quota|bandwidth|traffic|حجم)")

    /** Auto-disconnect window for volume-limited connections, in seconds. */
    const val AUTO_DISCONNECT_SECONDS: Long = 60L * 60L
    const val AUTO_DISCONNECT_ENABLED: Boolean = true

    data class VolumeInfo(
        val isVolume: Boolean,
        val totalBytes: Long?,
        val label: String,
    ) {
        companion object {
            val UNKNOWN = VolumeInfo(false, null, "—")
            val UNLIMITED = VolumeInfo(false, null, "نامحدود")
        }
    }

    /** Inspect a remark (the part after ``#``) for volume hints. */
    fun detectFromName(remark: String): VolumeInfo {
        if (remark.isBlank()) return VolumeInfo.UNKNOWN

        val hasKeyword = LIMIT_KEYWORDS.containsMatchIn(remark)
        val gb = GB_PATTERN.find(remark)
        val mb = MB_PATTERN.find(remark)
        val time = TIME_PATTERN.find(remark)

        val totalBytes: Long? = when {
            gb != null -> (gb.groupValues[1].replace(",", ".").toFloat() * 1024f * 1024f * 1024f).toLong()
            mb != null -> (mb.groupValues[1].replace(",", ".").toFloat() * 1024f * 1024f).toLong()
            else -> null
        }

        val isVolume = totalBytes != null || hasKeyword || time != null
        if (!isVolume) return VolumeInfo.UNKNOWN

        val label = when {
            totalBytes != null -> {
                val gbValue = totalBytes.toFloat() / (1024f * 1024f * 1024f)
                if (gbValue >= 1f) String.format("%.1f GB", gbValue)
                else "${totalBytes / (1024L * 1024L)} MB"
            }
            time != null -> {
                val amount = time.groupValues[1].toInt()
                val unit = time.groupValues[2].lowercase()
                when {
                    unit.startsWith("w") -> "${amount}w"
                    unit.startsWith("d") -> "${amount}d"
                    else -> "${amount}h"
                }
            }
            else -> "حجمی"
        }

        return VolumeInfo(true, totalBytes, label)
    }

    /** Convenience: extract the remark from a ServerRecord's raw config URI. */
    fun detectFromServer(server: ServerRecord): VolumeInfo {
        val raw = server.raw
        val remark = raw.substringAfter("#", server.name)
        return detectFromName(remark)
    }
}
