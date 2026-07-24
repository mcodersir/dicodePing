package ir.dicode.ping.data

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ServerPolicyTest {
    private fun server(ping: Int, code: String = "DE", country: String = "Germany") = ServerRecord(
        id = "id",
        raw = "raw",
        name = "server",
        protocol = "VLESS",
        host = "example.com",
        port = 443,
        sourceId = "default",
        sourceName = "default",
        pingMs = ping,
        pingKind = "PROXY_HTTP",
        ip = "1.2.3.4",
        country = country,
        countryCode = code,
        healthy = true,
    )

    @Test
    fun automaticModeRejectsSub70Latency() {
        assertFalse(ServerPolicy.isAutoEligible(server(69)))
        assertTrue(ServerPolicy.isAutoEligible(server(70)))
    }

    @Test
    fun iranLocationsAreRestricted() {
        assertTrue(ServerPolicy.isRestricted(server(90, code = "IR", country = "Iran")))
        assertTrue(ServerPolicy.isRestricted(server(90, code = "", country = "ایران")))
        assertFalse(ServerPolicy.isAutoEligible(server(90, code = "IR", country = "Iran")))
    }
}
