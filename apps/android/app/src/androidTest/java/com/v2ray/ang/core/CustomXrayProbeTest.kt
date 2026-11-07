package com.v2ray.ang.core

import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import java.net.ServerSocket
import java.net.InetAddress
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread

class CustomXrayProbeTest {
    @Test fun blockFirstServerlessConfigUsesItsRoutingRulesForRealHttp() {
        CoreNativeManager.initCoreEnv(InstrumentationRegistry.getInstrumentation().targetContext)
        val listener = ServerSocket(0, 4, InetAddress.getByName("127.0.0.1"))
        val hits = AtomicInteger()
        val worker = thread(isDaemon = true) {
            runCatching { while (!listener.isClosed) listener.accept().use { client ->
                client.soTimeout = 5000
                val reader = client.getInputStream().bufferedReader()
                while (!reader.readLine().isNullOrEmpty()) { }
                hits.incrementAndGet()
                client.getOutputStream().write("HTTP/1.1 204 No Content\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".toByteArray())
            } }
        }
        val config = """{"inbounds":[],"outbounds":[{"tag":"block","protocol":"blackhole"},{"tag":"allowed","protocol":"freedom"}],"routing":{"rules":[{"type":"field","ip":["127.0.0.1"],"outboundTag":"allowed"}]}}"""
        val url = "http://127.0.0.1:${listener.localPort}/generate_204"
        try {
            assertTrue("The old forced-first-outbound probe must reproduce the false negative", CoreNativeManager.measureOutboundDelay(config, url) < 0)
            assertEquals(0, hits.get())
            val delay = CustomXrayProbe().use { it.measure(config, url) }
            assertTrue("Full routing must pass a real 204 transaction", delay > 0)
            assertTrue(hits.get() > 0)
        } finally { listener.close(); worker.join(1000) }
    }
}
