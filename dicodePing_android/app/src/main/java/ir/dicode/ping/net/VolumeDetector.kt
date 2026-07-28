package ir.dicode.ping.net

import ir.dicode.ping.data.ServerRecord
import java.util.regex.Pattern

/**
 * Volume-based config detection — mirrors the desktop ``volume.py``.
 *
 * Two sources of volume information are supported:
 *
 * 1. The ``Subscription-Userinfo`` HTTP header (the v2rayN / Nekoray
 *    standard).  This is the *real* remaining-volume number that the
 *    user asked for in v1.6.0-rc.2.  When the user taps "Fetch volumes"
 *    the scanner issues HEAD requests in parallel for every enabled
 *    subscription URL and parses this header.
 *
 * 2. A remark-based heuristic (fallback).  Many free servers embed a
 *    quota hint in the remark (#name), e.g. ``10GB``, ``30d``,
 *    ``Volume``.  When no header is available, we fall back to this
 *    best-effort detection.
 *
 * When a server is detected as volume-limited and the user connects to
 * it, the VPN service arms an auto-disconnect timer (default one hour).
 */
object VolumeDetector {
    private val GB_PATTERN = Regex("(?i)\\b(\\d+(?:[.,]\\d+)?)\\s*(gb|gig|g)\\b(?!\\s*hz)")
    private val MB_PATTERN = Regex("(?i)\\b(\\d+(?:[.,]\\d+)?)\\s*(mb|meg|m)\\b(?!\\s*hz)")
    private val TIME_PATTERN = Regex("(?i)\\b(\\d+)\\s*(d|day|days|h|hr|hour|hours|w|week|weeks)\\b")
    private val LIMIT_KEYWORDS = Regex("(?i)(volume|vol|limit|data|gb|mb|quota|bandwidth|traffic|حجم)")

    /** Regex for the ``Subscription-Userinfo`` header value. */
    private val USERINFO_PATTERN = Pattern.compile(
        "upload\\s*=\\s*(\\d+)\\s*;\\s*download\\s*=\\s*(\\d+)\\s*;\\s*total\\s*=\\s*(\\d+)(?:\\s*;\\s*expire\\s*=\\s*(\\d+))?",
        Pattern.CASE_INSENSITIVE,
    )

    /** Auto-disconnect window for volume-limited connections, in seconds. */
    const val AUTO_DISCONNECT_SECONDS: Long = 60L * 60L
    const val AUTO_DISCONNECT_ENABLED: Boolean = true

    data class VolumeInfo(
        val isVolume: Boolean,
        val totalBytes: Long?,
        val usedBytes: Long?,
        val remainingBytes: Long?,
        val label: String,
        val source: String,
    ) {
        companion object {
            val UNKNOWN = VolumeInfo(false, null, null, null, "—", "none")
            val UNLIMITED = VolumeInfo(false, null, null, null, "نامحدود", "none")
        }
    }

    /** Parsed ``Subscription-Userinfo`` header. */
    data class SubscriptionQuota(
        val uploadBytes: Long,
        val downloadBytes: Long,
        val totalBytes: Long,
        val expireUnix: Long?,
    ) {
        val usedBytes: Long get() = uploadBytes + downloadBytes
        val remainingBytes: Long get() = maxOf(0L, totalBytes - usedBytes)
        val ratio: Float get() = if (totalBytes == 0L) 0f else minOf(1f, maxOf(0f, usedBytes.toFloat() / totalBytes))
    }

    /** Parse a ``Subscription-Userinfo`` header value, or return null. */
    fun parseUserinfo(header: String?): SubscriptionQuota? {
        if (header.isNullOrBlank()) return null
        val m = USERINFO_PATTERN.matcher(header) ?: return null
        if (!m.find()) return null
        return try {
            SubscriptionQuota(
                uploadBytes = m.group(1)?.toLongOrNull() ?: 0L,
                downloadBytes = m.group(2)?.toLongOrNull() ?: 0L,
                totalBytes = m.group(3)?.toLongOrNull() ?: 0L,
                expireUnix = m.group(4)?.toLongOrNull(),
            )
        } catch (_: Exception) {
            null
        }
    }

    /** Render a short human-readable label like ``3.2 / 10.0 GB``. */
    fun formatLabel(quota: SubscriptionQuota): String {
        val used = quota.usedBytes
        val total = quota.totalBytes
        val remaining = quota.remainingBytes
        val parts = mutableListOf<String>()
        parts.add("${gbStr(used)} / ${gbStr(total)}")
        if (remaining in 1 until total) parts.add("(${gbStr(remaining)} باقی)")
        return parts.joinToString(" • ")
    }

    private fun gbStr(bytes: Long): String {
        val gb = bytes.toFloat() / (1024f * 1024f * 1024f)
        return if (gb >= 1f) String.format("%.1f GB", gb)
        else "${bytes / (1024L * 1024L)} MB"
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

        return VolumeInfo(true, totalBytes, null, totalBytes, label, "remark")
    }

    /** Convenience: extract the remark from a ServerRecord's raw config URI. */
    fun detectFromServer(server: ServerRecord): VolumeInfo {
        val raw = server.raw
        val remark = raw.substringAfter("#", server.name)
        return detectFromName(remark)
    }
}

