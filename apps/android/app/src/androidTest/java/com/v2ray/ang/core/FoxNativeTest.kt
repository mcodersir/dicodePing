package com.v2ray.ang.core

import androidx.test.platform.app.InstrumentationRegistry
import com.v2ray.ang.BuildConfig
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
            assertTrue(process.inputStream.bufferedReader().readText().contains(BuildConfig.VERSION_NAME))
        } finally { if (process.isAlive) process.destroyForcibly() }
        assertTrue(FoxAccounts.roots().contains("BEGIN CERTIFICATE"))
        // Invalid input fails privately without making an authentication request.
        val error = runCatching { FoxAccounts.request(context, JSONObject().put("operation", "login").put("email", "invalid").put("password", "sentinel-never-saved")) }.exceptionOrNull()
        assertTrue(error is FoxError); assertEquals("input", (error as FoxError).code)
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
            val group = MmkvManager.decodeServerConfig(guid)!!.subscriptionId
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
