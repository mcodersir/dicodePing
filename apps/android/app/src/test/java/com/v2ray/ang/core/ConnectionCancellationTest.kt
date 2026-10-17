package com.v2ray.ang.core

import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test

class ConnectionCancellationTest {
    @Test fun aLateRestartReplyDoesNotStartAfterManualDisconnect() {
        var epoch = ""
        val requests = ConnectionRequests({ epoch }, { epoch = it })
        var reply: (Boolean) -> Unit = {}
        var starts = 0
        requests.restart({ _, result -> reply = result }) { starts++ }
        val oldRequest = requests.version()
        requests.cancel()
        reply(false)
        assertEquals(0, starts)
        assertFalse(requests.isCurrent(oldRequest))
        requests.restart({ _, result -> reply = result }) { starts++ }
        reply(false)
        assertEquals(1, starts)
    }

    @Test fun theDaemonSeesAStopEvenAfterItsOldReceiverUnregistered() {
        var storedEpoch = ""
        val ui = ConnectionRequests({ storedEpoch }, { storedEpoch = it })
        val daemon = ConnectionRequests({ storedEpoch }, { storedEpoch = it })
        val restart = daemon.version()
        ui.cancel()
        assertFalse(daemon.isCurrent(restart))
        assertTrue(daemon.isCurrent(ui.version()))
    }
}
