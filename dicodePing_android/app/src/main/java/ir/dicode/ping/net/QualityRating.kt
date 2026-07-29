package ir.dicode.ping.net

/**
 * Quality detection — mirrors the desktop ``volume.rate_quality`` function.
 *
 * Buckets are tuned for real-world proxy traffic:
 *   - Excellent: ping ≤ 180 ms and jitter ≤ 25 ms
 *   - Good:      ping ≤ 400 ms
 *   - Fair:      ping ≤ 900 ms
 *   - Poor:      ping > 900 ms or no ping
 */
object QualityRating {
    enum class Bucket(val labelFa: String, val labelEn: String) {
        EXCELLENT("عالی", "Excellent"),
        GOOD("خوب", "Good"),
        FAIR("متوسط", "Fair"),
        POOR("ضعیف", "Poor");

        companion object {
            fun fromKey(key: String): Bucket = when (key) {
                "excellent" -> EXCELLENT
                "good" -> GOOD
                "fair" -> FAIR
                else -> POOR
            }
        }
    }

    data class Rating(val bucket: Bucket, val score: Int)

    fun rate(pingMs: Int?, jitterMs: Float? = null): Rating {
        if (pingMs == null || pingMs <= 0) {
            return Rating(Bucket.POOR, 0)
        }
        val j = jitterMs ?: 0f
        return when {
            pingMs <= 180 && j <= 25f -> {
                val score = 95 - minOf(15, maxOf(0, (pingMs - 80) / 6))
                Rating(Bucket.EXCELLENT, maxOf(80, score))
            }
            pingMs <= 400 -> {
                val score = 75 - minOf(15, (pingMs - 180) / 15)
                Rating(Bucket.GOOD, maxOf(55, score))
            }
            pingMs <= 900 -> {
                val score = 50 - minOf(15, (pingMs - 400) / 35)
                Rating(Bucket.FAIR, maxOf(30, score))
            }
            else -> {
                val score = maxOf(0, 25 - (pingMs - 900) / 50)
                Rating(Bucket.POOR, score)
            }
        }
    }
}
