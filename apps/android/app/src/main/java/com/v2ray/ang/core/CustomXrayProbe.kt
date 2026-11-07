package com.v2ray.ang.core

import java.util.concurrent.atomic.AtomicBoolean
import libv2ray.CoreCallbackHandler

/** A complete custom configuration is a route, not its first outbound.
 * Runs in the test-service process, without a VPN/TUN or public listener.
 * The execution limiter keeps its DNS/router lifetime exclusive of other tests.
 */
internal class CustomXrayProbe : AutoCloseable {
    private val closed = AtomicBoolean(false)
    private val controller = CoreNativeManager.newCoreController(object : CoreCallbackHandler {
        override fun startup(): Long = 0
        override fun shutdown(): Long = 0
        override fun onEmitStatus(code: Long, message: String?): Long = 0
    })
    fun measure(config: String, url: String): Long = NativeProbeLifetime.exclusive {
        check(!closed.get()) { "Probe cancelled" }
        try {
            controller.startLoop(config, 0)
            if (closed.get()) { controller.stopLoop(); return@exclusive -1 }
            controller.measureDelay(url)
        } finally { close() }
    }
    override fun close() {
        if (closed.compareAndSet(false, true)) controller.stopLoop()
    }
}
