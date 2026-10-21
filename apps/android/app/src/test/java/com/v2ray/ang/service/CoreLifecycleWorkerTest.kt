package com.v2ray.ang.service

import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class CoreLifecycleWorkerTest {
    @Test fun blockedStartupDoesNotBlockCallerAndTeardownPrecedesTheNextStart() {
        val entered = CountDownLatch(1)
        val release = CountDownLatch(1)
        val complete = CountDownLatch(1)
        val events = java.util.Collections.synchronizedList(mutableListOf<String>())
        try {
            CoreLifecycleWorker.executor.execute { entered.countDown(); release.await(3, TimeUnit.SECONDS); events.add("start") }
            assertTrue(entered.await(1, TimeUnit.SECONDS))
            CoreLifecycleWorker.executor.execute { events.add("stop") }
            CoreLifecycleWorker.executor.execute { events.add("next"); complete.countDown() }
            assertTrue(events.isEmpty()) // The caller is responsive while network startup is blocked.
        } finally { release.countDown() }
        assertTrue(complete.await(2, TimeUnit.SECONDS))
        assertEquals(listOf("start", "stop", "next"), events.toList())
    }
}
