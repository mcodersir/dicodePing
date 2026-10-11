package com.v2ray.ang.core

import androidx.test.platform.app.InstrumentationRegistry
import com.v2ray.ang.handler.AngConfigManager
import com.v2ray.ang.handler.MmkvManager
import org.junit.Assert.*
import org.junit.Test
import java.net.ServerSocket
import java.net.Socket
import kotlin.concurrent.thread

class SingBoxNativeTest {
    @Test fun bundledAndroidCoreAcceptsEveryNativeConnectionForm() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val ca = instrumentation.context.assets.open("native-test-ca.pem").bufferedReader().use { it.readText() }
        val executable = java.io.File(context.applicationInfo.nativeLibraryDir, "libsingbox.so")
        for (kind in NativeProfileTemplates.kinds) {
            val raw = NativeProfileTemplates.build(kind, "vpn.example.com", 443, "test", "abcdefghijklmnopqrstuvwxyz123456", if (kind == "openvpn-client") ca else "", "Native test")
            val file = java.io.File(context.cacheDir, "native-check-$kind.json")
            file.writeText(SingBoxConfig.prepare(raw, 21512))
            val process = ProcessBuilder(executable.absolutePath, "check", "-c", file.absolutePath).redirectErrorStream(true).start()
            try {
                assertTrue("Native configuration check timed out: $kind", process.waitFor(15, java.util.concurrent.TimeUnit.SECONDS))
                val output = process.inputStream.bufferedReader().readText()
                assertEquals("Unsupported native form $kind: $output", 0, process.exitValue())
            } finally {
                if (process.isAlive) process.destroyForcibly()
                file.delete()
            }
        }
    }

    @Test fun nativeHelperMakesRealHttpRequestsAndCleansUpItsListener() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val port = ServerSocket(0).use { it.localPort }
        ServerSocket(0).use { http ->
            val server = thread {
                http.accept().use { socket ->
                    val input = socket.getInputStream().bufferedReader()
                    while (input.readLine()?.isNotEmpty() == true) { }
                    socket.getOutputStream().write("HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK".toByteArray())
                }
            }
            val raw = """{"inbounds":[],"outbounds":[{"type":"direct","tag":"proxy"}],"route":{"final":"proxy"}}"""
            SingBoxProcess(context).use { helper ->
                helper.start(raw, port)
                assertTrue(helper.measure(port, "http://127.0.0.1:${http.localPort}/") > 0)
            }
            server.join(5000)
            assertFalse(server.isAlive)
        }
        assertTrue(runCatching { Socket("127.0.0.1", port).close() }.isFailure)
    }

    @Test fun nativeEndpointProfilesAndCustomExportsRoundTripWithoutLosingJson() {
        val group = "450-native-test"
        MmkvManager.encodeSubscription(group, com.v2ray.ang.dto.entities.SubscriptionItem(remarks = "Native test", enabled = false))
        val raw = NativeProfileTemplates.build("openconnect", "vpn.example.com", 443, "test", "test", "", "Cisco test")
        try {
            assertEquals(1, AngConfigManager.importBatchConfig(raw, group, true).first)
            val first = MmkvManager.decodeAllServerList().first { MmkvManager.decodeServerConfig(it)?.subscriptionId == group }
            assertEquals(raw, MmkvManager.decodeServerRaw(first))
            val link = "dicode-json://" + java.util.Base64.getUrlEncoder().withoutPadding().encodeToString(raw.toByteArray())
            assertEquals(1, AngConfigManager.importBatchConfig(link, group, false).first)
            val imported = MmkvManager.decodeAllServerList().first { MmkvManager.decodeServerConfig(it)?.subscriptionId == group }
            assertEquals(raw, MmkvManager.decodeServerRaw(imported))
        } finally {
            MmkvManager.decodeAllServerList().filter { MmkvManager.decodeServerConfig(it)?.subscriptionId == group }.forEach(MmkvManager::removeServer)
            MmkvManager.removeSubscription(group)
        }
    }
}
