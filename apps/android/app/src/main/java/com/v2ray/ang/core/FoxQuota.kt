package com.v2ray.ang.core

/** Actual provider allowance; an unknown quota must never appear as an unused 50 GB. */
internal data class FoxQuota private constructor(val maximum: Long, val remaining: Long) {
    val used: Long get() = maximum - remaining
    val fraction: Float get() = (used.toDouble() / maximum).toFloat()
    companion object {
        fun from(maximum: Long, remaining: Long): FoxQuota? =
            if (maximum > 0 && remaining >= 0) FoxQuota(maximum, remaining.coerceAtMost(maximum)) else null
    }
}
