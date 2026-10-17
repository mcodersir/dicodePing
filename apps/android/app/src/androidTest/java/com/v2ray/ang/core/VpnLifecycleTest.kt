package com.v2ray.ang.core

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.VpnService
import androidx.core.content.ContextCompat
import androidx.test.platform.app.InstrumentationRegistry
import com.v2ray.ang.AppConfig
import com.v2ray.ang.dto.entities.ProfileItem
import com.v2ray.ang.enums.EConfigType
import com.v2ray.ang.handler.MmkvManager
import com.v2ray.ang.handler.SettingsManager
import com.v2ray.ang.helper.MessageHelper
import org.junit.Assert.*
import org.junit.Test
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

/** Runs the production VPN service in its daemon process, not a mock controller. */
class VpnLifecycleTest {
    @Test fun hevVpnSurvivesAnUnreachableTestUrlAndManualStopReleasesItsListener() = exercise(true)
    @Test fun nativeVpnSurvivesAnUnreachableTestUrlAndManualStopReleasesItsListener() = exercise(false)

    private fun exercise(hev: Boolean) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        fun shell(command: String): String = instrumentation.uiAutomation.executeShellCommand(command).use {
            android.os.ParcelFileDescriptor.AutoCloseInputStream(it).bufferedReader().readText()
        }
        shell("appops set ${context.packageName} ACTIVATE_VPN allow")
        assertNull("The emulator must grant VPN permission", VpnService.prepare(context))
        val keys = listOf(AppConfig.PREF_MODE, AppConfig.PREF_USE_HEV_TUNNEL, AppConfig.PREF_DELAY_TEST_URL, AppConfig.PREF_PER_APP_PROXY, AppConfig.PREF_VPN_BYPASS_LAN)
        val old = keys.filterNot { it == AppConfig.PREF_USE_HEV_TUNNEL || it == AppConfig.PREF_PER_APP_PROXY }.associateWith { MmkvManager.decodeSettingsString(it) }
        val oldHev = MmkvManager.decodeSettingsBool(AppConfig.PREF_USE_HEV_TUNNEL, true)
        val oldPerApp = MmkvManager.decodeSettingsBool(AppConfig.PREF_PER_APP_PROXY, false)
        val selected = MmkvManager.getSelectServer()
        val oldRules = MmkvManager.decodeRoutingRulesets()
        val fixtureRules = oldRules.orEmpty().toMutableList()
        fixtureRules.add(0, com.v2ray.ang.dto.entities.RulesetItem(outboundTag = "proxy", ip = arrayListOf("192.0.2.10/32")))
        MmkvManager.encodeRoutingRulesets(fixtureRules)
        val events = LinkedBlockingQueue<Int>()
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(c: Context?, intent: Intent?) { events.offer(intent?.getIntExtra("key", 0) ?: 0) }
        }
        ContextCompat.registerReceiver(context, receiver, IntentFilter(AppConfig.BROADCAST_ACTION_ACTIVITY), ContextCompat.RECEIVER_NOT_EXPORTED)
        val upstream = ServerSocket(0, 16, InetAddress.getByName("127.0.0.1"))
        val requests = java.util.concurrent.atomic.AtomicInteger()
        val worker = thread(isDaemon = true) {
            while (!upstream.isClosed) {
                val socket = runCatching { upstream.accept() }.getOrNull() ?: break
                thread(isDaemon = true) {
                    runCatching { socket.use { client ->
                        client.soTimeout = 5000
                        val input = java.io.DataInputStream(client.getInputStream())
                        val output = client.getOutputStream()
                        check(input.readUnsignedByte() == 5)
                        input.readFully(ByteArray(input.readUnsignedByte()))
                        output.write(byteArrayOf(5, 0)); output.flush()
                        check(input.readUnsignedByte() == 5); check(input.readUnsignedByte() == 1); input.readUnsignedByte()
                        when (input.readUnsignedByte()) {
                            1 -> input.readFully(ByteArray(4))
                            3 -> input.readFully(ByteArray(input.readUnsignedByte()))
                            4 -> input.readFully(ByteArray(16))
                            else -> error("Invalid SOCKS destination")
                        }
                        val port = input.readUnsignedShort()
                        // The configured health endpoint is deliberately unavailable.
                        if (port == 9) { output.write(byteArrayOf(5, 5, 0, 1, 0, 0, 0, 0, 0, 0)); output.flush(); return@use }
                        output.write(byteArrayOf(5, 0, 0, 1, 127, 0, 0, 1, 0, 0)); output.flush()
                        val header = StringBuilder()
                        while (!header.endsWith("\r\n\r\n") && header.length < 8192) header.append(input.readUnsignedByte().toChar())
                        requests.incrementAndGet()
                        output.write("HTTP/1.1 200 OK\r\nContent-Length: 12\r\nConnection: close\r\n\r\nVPN fixture!".toByteArray()); output.flush()
                    } }
                }
            }
        }
        var guid = ""
        try {
            MmkvManager.encodeSettings(AppConfig.PREF_MODE, "VPN")
            MmkvManager.encodeSettings(AppConfig.PREF_VPN_BYPASS_LAN, "2")
            MmkvManager.encodeSettings(AppConfig.PREF_USE_HEV_TUNNEL, hev)
            MmkvManager.encodeSettings(AppConfig.PREF_PER_APP_PROXY, false)
            MmkvManager.encodeSettings(AppConfig.PREF_DELAY_TEST_URL, "http://127.0.0.1:9/generate_204")
            guid = MmkvManager.encodeServerConfig("", ProfileItem(configType = EConfigType.SOCKS, remarks = "VPN lifecycle fixture", server = "127.0.0.1", serverPort = upstream.localPort.toString()))
            LauncherManager.startService(context, guid)
            val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(25)
            var ready = false
            while (System.nanoTime() < deadline && !ready) {
                val event = events.poll(1, TimeUnit.SECONDS)
                assertNotEquals("VPN service reported a startup failure", AppConfig.MSG_STATE_START_FAILURE, event)
                ready = event == AppConfig.MSG_STATE_START_SUCCESS
            }
            assertTrue("Production VPN did not start", ready)
            // 4.9.1 used to stop the entire VPN when that test endpoint failed.
            Thread.sleep(14000)
            assertFalse("An unavailable test URL stopped the VPN", events.contains(AppConfig.MSG_STATE_START_FAILURE))
            val proxyPort = SettingsManager.getSocksPort()
            assertTrue("The active service must still carry HTTP", AetherDelayTester.requestDelay(proxyPort, "http://example.com:8080/success") > 0)
            assertTrue(requests.get() > 0)
            // Shell UID is included in the VPN, while this app's local fixture is
            // excluded. This request must enter the actual kernel TUN interface.
            val pipes = instrumentation.uiAutomation.executeShellCommandRw("toybox nc -w 8 -W 8 192.0.2.10 8080")
            val request = android.os.ParcelFileDescriptor.AutoCloseOutputStream(pipes[1])
            val tunneled = try {
                // Keep stdin open until the response arrives. A pipe that closes
                // after printf sends an early TCP FIN through the tunnel.
                request.write("GET /tun HTTP/1.1\r\nHost: example.com\r\nConnection: close\r\n\r\n".toByteArray())
                request.flush()
                android.os.ParcelFileDescriptor.AutoCloseInputStream(pipes[0]).bufferedReader().use { it.readText() }
            } finally { request.close() }
            assertTrue("No HTTP response through the kernel TUN: $tunneled", tunneled.contains("VPN fixture!"))
            LauncherManager.stopService(context)
            var closed = false
            repeat(50) {
                if (!closed) { closed = runCatching { Socket("127.0.0.1", proxyPort).close() }.isFailure; Thread.sleep(100) }
            }
            assertTrue("Manual stop left the core listener running", closed)
            Thread.sleep(1500)
            assertTrue("A stale request restarted the core", runCatching { Socket("127.0.0.1", proxyPort).close() }.isFailure)
        } finally {
            LauncherManager.stopService(context)
            Thread.sleep(500)
            if (guid.isNotEmpty()) MmkvManager.removeServer(guid)
            selected?.let(MmkvManager::setSelectServer)
            MmkvManager.encodeRoutingRulesets(oldRules.orEmpty().toMutableList())
            old.forEach { (key, value) -> if (value == null) MmkvManager.encodeSettings(key, null as String?) else MmkvManager.encodeSettings(key, value) }
            MmkvManager.encodeSettings(AppConfig.PREF_USE_HEV_TUNNEL, oldHev)
            MmkvManager.encodeSettings(AppConfig.PREF_PER_APP_PROXY, oldPerApp)
            context.unregisterReceiver(receiver)
            upstream.close(); worker.join(1000)
        }
    }
}
