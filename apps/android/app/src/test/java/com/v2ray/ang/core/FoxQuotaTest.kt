package com.v2ray.ang.core

import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test

class FoxQuotaTest {
    @Test fun providerAllowance() {
        val quota = FoxQuota.from(50_000_000_000L, 30_000_000_000L)!!
        assertEquals(20_000_000_000L, quota.used)
        assertEquals(0.4f, quota.fraction)
    }
    @Test fun malformedAndUnknownQuotas() {
        assertNull(FoxQuota.from(0, 0)); assertNull(FoxQuota.from(50, -1))
        assertEquals(0f, FoxQuota.from(50, 80)!!.fraction)
        assertEquals(1f, FoxQuota.from(Long.MAX_VALUE, 0)!!.fraction)
    }
}
