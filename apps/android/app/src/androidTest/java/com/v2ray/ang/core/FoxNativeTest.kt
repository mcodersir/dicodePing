package com.v2ray.ang.core

import androidx.test.platform.app.InstrumentationRegistry
import com.v2ray.ang.handler.MmkvManager
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.util.UUID
import java.util.concurrent.TimeUnit

class FoxNativeTest {
    @Test fun helperRunsAndLoadsAndroidTrustStoreWithoutLeakingCredentials() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val executable = File(context.applicationInfo.nativeLibraryDir, "libdicodefox.so")
        val process = ProcessBuilder(executable.absolutePath, "--version").redirectErrorStream(true).start()
        try {
            assertTrue(process.waitFor(10, TimeUnit.SECONDS)); assertEquals(0, process.exitValue())
            assertTrue(process.inputStream.bufferedReader().readText().contains("4.7.2"))
        } finally { if (process.isAlive) process.destroyForcibly() }
        assertTrue(FoxAccounts.roots().contains("BEGIN CERTIFICATE"))
        // Invalid input fails privately without making an authentication request.
        val error = runCatching { FoxAccounts.request(context, JSONObject().put("operation", "login").put("email", "invalid").put("password", "sentinel-never-saved")) }.exceptionOrNull()
        assertTrue(error is FoxError); assertEquals("input", (error as FoxError).code)
    }
    @Test fun nativeXrayBridgeMovesAnHttpRequestThroughTheSocksEndpoint() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        CoreNativeManager.initCoreEnv(context)
        val server = java.net.ServerSocket(0, 1, java.net.InetAddress.getByName("127.0.0.1"))
        val requests = java.util.concurrent.atomic.AtomicInteger()
        val worker = kotlin.concurrent.thread(isDaemon = true) {
            server.accept().use { client ->
                client.soTimeout = 10000
                val input = java.io.DataInputStream(client.getInputStream()); val output = client.getOutputStream()
                check(input.readUnsignedByte() == 5)
                val methods = ByteArray(input.readUnsignedByte()); input.readFully(methods)
                output.write(byteArrayOf(5, 0)); output.flush()
                check(input.readUnsignedByte() == 5); check(input.readUnsignedByte() == 1); input.readUnsignedByte()
                when (input.readUnsignedByte()) {
                    1 -> input.readFully(ByteArray(4))
                    3 -> input.readFully(ByteArray(input.readUnsignedByte()))
                    4 -> input.readFully(ByteArray(16))
                    else -> error("Invalid SOCKS address")
                }
                input.readUnsignedShort()
                output.write(byteArrayOf(5, 0, 0, 1, 127, 0, 0, 1, 0, 0)); output.flush()
                val header = StringBuilder()
                while (!header.endsWith("\r\n\r\n") && header.length < 8192) header.append(input.readUnsignedByte().toChar())
                check(header.startsWith("GET ")); requests.incrementAndGet()
                Thread.sleep(25) // Keep the measured success distinguishable from a zero/error result.
                output.write("HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK".toByteArray()); output.flush()
            }
        }
        try {
            val config = SingBoxConfig.xrayBridge(server.localPort, com.v2ray.ang.util.Utils.findRandomFreePort())
            assertEquals("socks", config.getAsJsonArray("outbounds")[0].asJsonObject.get("protocol").asString)
            val delay = CoreNativeManager.measureOutboundDelay(config.toString(), "http://fox-fixture.invalid/success")
            assertTrue("Native SOCKS bridge returned $delay", delay > 0); assertEquals(1, requests.get())
        } finally { server.close(); worker.join(1500) }
    }
    @Test fun encryptedMultiAccountVaultAndSingleProfileSurviveUpdatesAndLocalDeletion() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val id = UUID.randomUUID().toString().replace("-", "")
        val second = UUID.randomUUID().toString().replace("-", "")
        val account = FoxAccount(id, "REC", JSONObject().put("email", "fixture@example.test").put("access_token", "private-session-sentinel"), JSONObject().put("quota_max", 50000000000L))
        try {
            FoxAccounts.save(context, account, true)
            FoxAccounts.save(context, FoxAccount(second, "US", JSONObject().put("email", "second@example.test"), JSONObject()), true)
            val ciphertext = File(context.noBackupFilesDir, "fox-accounts.enc").readBytes().toString(Charsets.UTF_8)
            assertFalse(ciphertext.contains("private-session-sentinel")); assertFalse(ciphertext.contains(account.email))
            val guid = FoxAccounts.sync(context, account)
            account.country = "DE"; FoxAccounts.save(context, account)
            assertEquals(guid, FoxAccounts.sync(context, account))
            val saved = MmkvManager.decodeServerConfig(guid)!!
            assertEquals(com.v2ray.ang.enums.EConfigType.SOCKS, saved.configType)
            assertEquals("127.0.0.1", saved.server); assertEquals("7854", saved.serverPort)
            assertEquals(id, FoxAccounts.profile(saved)!!.accountId)
            val runtime = CoreConfigManager.getV2rayConfig(context, guid)
            assertTrue(runtime.status); assertEquals(id, runtime.foxAccountId); assertEquals(7854, runtime.foxPort)
            assertFalse(runtime.content.contains("private-session-sentinel"))
            val group = saved.subscriptionId
            assertEquals(1, MmkvManager.decodeServerList(group).size)
            assertEquals("DE", FoxAccounts.profile(MmkvManager.decodeServerRaw(guid)!!)!!.country)
            FoxAccounts.updateSession(context, id, JSONObject().put("email", account.email).put("access_token", "new-token"))
            assertEquals("DE", FoxAccounts.get(context, id).country)
            FoxAccounts.remove(context, id); FoxAccounts.save(context, account)
            assertFalse(FoxAccounts.list(context).any { it.id == id }); assertNotNull(FoxAccounts.get(context, second))
            assertNull(MmkvManager.decodeServerConfig(guid))
        } finally { FoxAccounts.remove(context, id); FoxAccounts.remove(context, second) }
    }
}
