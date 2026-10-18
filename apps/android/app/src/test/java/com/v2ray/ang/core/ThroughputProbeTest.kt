package com.v2ray.ang.core

import kotlinx.coroutines.runBlocking
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import java.io.DataInputStream
import java.io.IOException
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import kotlin.concurrent.thread

class ThroughputProbeTest {
    @Test fun actualPayloadIsMeasuredAndAnHtmlPortalIsRejected() = runBlocking {
        for (portal in listOf(false, true)) {
            ServerSocket(0, 50, InetAddress.getLoopbackAddress()).use { server ->
                val received = java.util.concurrent.atomic.AtomicLong()
                val loop = thread(isDaemon = true) {
                    repeat(2) {
                        val socket = server.accept()
                        socket.use {
                            val input = it.getInputStream()
                            fun line(): String {
                                val bytes = java.io.ByteArrayOutputStream()
                                while (true) { val b = input.read(); if (b < 0 || b == 10) break; if (b != 13) bytes.write(b) }
                                return bytes.toString("US-ASCII")
                            }
                            val first = line()
                            var length = 0
                            while (true) {
                                val line = line()
                                if (line.isEmpty()) break
                                if (line.startsWith("Content-Length:", true)) length = line.substringAfter(':').trim().toInt()
                            }
                            if (length > 0) {
                                val buffer = ByteArray(8192)
                                var left = length
                                while (left > 0) {
                                    val n = input.read(buffer, 0, minOf(buffer.size, left)); if (n < 0) break
                                    received.addAndGet(n.toLong()); left -= n
                                }
                            }
                            val body = if (first.startsWith("GET")) "x".repeat(131072) else "ok"
                            val type = if (portal) "text/html" else "application/octet-stream"
                            it.getOutputStream().write(("HTTP/1.1 200 OK\r\nContent-Type: $type\r\nContent-Length: ${body.length}\r\nConnection: close\r\n\r\n"+body).toByteArray())
                        }
                    }
                }
                SocksStub().use { socks ->
                    val url = "http://127.0.0.1:${server.localPort}/"
                    val result = ProxyThroughputProbe.measure(socks.port, downloadUrl = url, uploadUrl = url)
                    if (portal) { assertNull(result.downloadMbps); assertNull(result.uploadMbps) }
                    else { assertTrue(result.downloadMbps!! > 0); assertTrue(result.uploadMbps!! > 0) }
                }
                loop.join(3000)
                assertEquals(65536L, received.get())
            }
        }
    }
    @Test fun slowValidatedDownloadProducesATimedSample() {
        ServerSocket(0, 50, InetAddress.getLoopbackAddress()).use { server ->
            val loop = thread(isDaemon = true) {
                server.accept().use { socket ->
                    val reader = socket.getInputStream().bufferedReader()
                    while (reader.readLine()?.isNotEmpty() == true) Unit
                    socket.getOutputStream().write(("HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\nContent-Length: 131072\r\n\r\n" + "a".repeat(65536)).toByteArray())
                    socket.getOutputStream().flush()
                    Thread.sleep(1000)
                }
            }
            SocksStub().use { socks ->
                val client = okhttp3.OkHttpClient.Builder()
                    .proxy(java.net.Proxy(java.net.Proxy.Type.SOCKS, java.net.InetSocketAddress("127.0.0.1", socks.port)))
                    .callTimeout(500, java.util.concurrent.TimeUnit.MILLISECONDS).build()
                try {
                    val result = ProxyThroughputProbe.sample(client, AetherDelayTester.ProbeCalls(), "http://127.0.0.1:${server.localPort}/", null)
                    assertNotNull(result)
                    assertTrue(result!! > 0)
                } finally { client.connectionPool.evictAll(); client.dispatcher.executorService.shutdown() }
            }
            loop.join(2000)
        }
    }

    private class SocksStub : AutoCloseable {
        private val server = ServerSocket(0, 50, InetAddress.getLoopbackAddress())
        val port: Int get() = server.localPort

        init {
            thread(isDaemon = true) {
                while (true) {
                    val client = try {
                        server.accept()
                    } catch (_: IOException) {
                        return@thread
                    }
                    thread(isDaemon = true) { runCatching { relay(client) } }
                }
            }
        }

        private fun relay(client: Socket) = client.use {
            val input = DataInputStream(client.getInputStream())
            val output = client.getOutputStream()
            input.readByte()
            repeat(input.readUnsignedByte()) { input.readByte() }
            output.write(byteArrayOf(5, 0))
            repeat(3) { input.readByte() }
            val host = when (input.readUnsignedByte()) {
                1 -> InetAddress.getByAddress(ByteArray(4).also(input::readFully)).hostAddress
                3 -> String(ByteArray(input.readUnsignedByte()).also(input::readFully))
                else -> return@use
            }
            val targetPort = input.readUnsignedShort()
            Socket(host, targetPort).use { target ->
                output.write(byteArrayOf(5, 0, 0, 1, 0, 0, 0, 0, 0, 0))
                thread(isDaemon = true) {
                    runCatching { client.getInputStream().copyTo(target.getOutputStream()) }
                }
                runCatching { target.getInputStream().copyTo(output) }
            }
        }

        override fun close() = server.close()
    }
}
