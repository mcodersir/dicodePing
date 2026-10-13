package com.v2ray.ang.handler

import kotlinx.coroutines.*
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
import java.io.IOException
import java.net.ServerSocket

class PoolNetworkTest {
    @Test fun localReadinessDoesNotDependOnGithub() = runBlocking<Unit> {
        ServerSocket(0).use { socket ->
            withTimeout(3000) { PoolNetwork.waitForListener { socket.localPort } }
        }
    }

    @Test fun sourceFailureUsesAnotherEndpoint() = runBlocking<Unit> {
        var calls = 0
        val events = mutableListOf<PoolProgress>()
        val channels = PoolNetwork.loadChannels({ url ->
            calls++
            if (url.contains("raw.githubusercontent.com")) throw IOException("unavailable")
            "t.me/example_channel"
        }, { events.add(it) })
        assertEquals(3, calls)
        assertEquals(listOf("example_channel"), channels)
        assertTrue(events.all { it.stage == "کانال‌ها" })
    }

    @Test fun slowSourceIsNotMisclassifiedAsVpnFailure() = runBlocking<Unit> {
        val result = PoolNetwork.loadChannels({ delay(2100); "t.me/example_channel" }, {})
        assertEquals(listOf("example_channel"), result)
    }

    @Test fun sourceErrorsKeepTheirOwnStage() = runBlocking<Unit> {
        try {
            PoolNetwork.loadChannels({ throw IOException("blocked") }, {})
            fail<Unit>("Expected source failure")
        } catch (error: IllegalStateException) {
            assertTrue(error.message.orEmpty().contains("فهرست کانال‌ها"))
            assertFalse(error.message.orEmpty().contains("اتصال ساب پیش‌فرض برقرار نشد"))
        }
    }
}
