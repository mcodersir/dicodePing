package com.v2ray.ang.core

import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.locks.StampedLock

/** A lease can be closed by a different coroutine/cancellation thread. */
internal object NativeProbeLifetime {
    private val lock = StampedLock()
    fun sharedLease(): AutoCloseable {
        val stamp = lock.readLock()
        val closed = AtomicBoolean(false)
        return AutoCloseable { if (closed.compareAndSet(false, true)) lock.unlockRead(stamp) }
    }
    fun <T> shared(block: () -> T): T = sharedLease().use { block() }
    fun <T> exclusive(block: () -> T): T {
        val stamp = lock.writeLock()
        return try { block() } finally { lock.unlockWrite(stamp) }
    }
}
