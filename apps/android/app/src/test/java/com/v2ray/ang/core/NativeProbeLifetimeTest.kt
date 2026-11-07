package com.v2ray.ang.core

import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

class NativeProbeLifetimeTest {
    @Test fun fullConfigWaitsForAnExitLeaseAndCancellationCanReleaseOnAnotherThread() {
        val lease = NativeProbeLifetime.sharedLease()
        val entered = CountDownLatch(1)
        val finished = CountDownLatch(1)
        val writer = thread { NativeProbeLifetime.exclusive { entered.countDown() }; finished.countDown() }
        assertFalse(entered.await(100, TimeUnit.MILLISECONDS))
        thread { lease.close(); lease.close() }.join(1000)
        assertTrue(finished.await(2, TimeUnit.SECONDS))
        writer.join(1000)
    }
}
