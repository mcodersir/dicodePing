package com.v2ray.ang.core

import android.content.Context
import com.v2ray.ang.handler.MmkvManager
import com.v2ray.ang.helper.MessageHelper
import io.mockk.*
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test

class ConnectionCancellationTest {
    @AfterEach fun cleanup() { unmockkAll() }

    @Test fun aLateRestartReplyDoesNotStartAfterManualDisconnect() {
        var epoch: String? = null
        mockkObject(MmkvManager, MessageHelper)
        every { MmkvManager.decodeSettingsString("dicode_connection_cancellation") } answers { epoch }
        every { MmkvManager.encodeSettings("dicode_connection_cancellation", any<String>()) } answers { epoch = secondArg(); true }
        val reply = slot<(Boolean) -> Unit>()
        every { MessageHelper.sendMsg2ServiceForResult(any(), any(), any(), capture(reply)) } just Runs
        every { MessageHelper.sendMsg2Service(any(), any(), any()) } just Runs
        val context = mockk<Context>()
        var starts = 0
        LauncherManager.restartServiceOrStart(context) { starts++ }
        val oldRequest = LauncherManager.connectionRequestVersion()
        LauncherManager.stopService(context)
        reply.captured(false)
        assertEquals(0, starts)
        assertFalse(LauncherManager.isConnectionRequestCurrent(oldRequest))
        LauncherManager.restartServiceOrStart(context) { starts++ }
        reply.captured(false)
        assertEquals(1, starts)
    }
}
