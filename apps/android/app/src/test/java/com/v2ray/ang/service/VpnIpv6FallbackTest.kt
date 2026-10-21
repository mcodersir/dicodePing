package com.v2ray.ang.service

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertSame
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Test

class VpnIpv6FallbackTest {

    private val calls = mutableListOf<String>()

    private fun interfaceOf(name: String): () -> String = {
        calls += name
        name
    }

    private fun failing(name: String, error: Exception): () -> String = {
        calls += name
        throw error
    }

    @Test
    fun `an interface without IPv6 is established once`() {
        val established = establishFallingBackToIpv4(false, interfaceOf("first"), interfaceOf("ipv4")) { calls += "refused" }

        assertEquals("first", established)
        assertEquals(listOf("first"), calls)
    }

    @Test
    fun `an interface the kernel lets take IPv6 is kept`() {
        val established = establishFallingBackToIpv4(true, interfaceOf("first"), interfaceOf("ipv4")) { calls += "refused" }

        assertEquals("first", established)
        assertEquals(listOf("first"), calls)
    }

    @Test
    fun `an interface refused with IPv6 is established again without it`() {
        // What Android throws when the kernel refuses the IPv6 address.
        val refusal = IllegalStateException("Cannot set address")
        var reported: Exception? = null

        val established = establishFallingBackToIpv4(true, failing("first", refusal), interfaceOf("ipv4")) {
            reported = it
            calls += "refused"
        }

        assertEquals("ipv4", established)
        assertEquals(listOf("first", "refused", "ipv4"), calls)
        assertSame(refusal, reported)
    }

    @Test
    fun `a failure without IPv6 stays a failure`() {
        val failure = IllegalStateException("no interface")

        // Without IPv6 asked for, nothing is tried again.
        assertSame(failure, assertThrows(IllegalStateException::class.java) {
            establishFallingBackToIpv4(false, failing("first", failure), interfaceOf("ipv4")) { calls += "refused" }
        })
        assertEquals(listOf("first"), calls)

        // With IPv6, the second try's failure is the one that ends the start.
        calls.clear()
        assertSame(failure, assertThrows(IllegalStateException::class.java) {
            establishFallingBackToIpv4(true, failing("first", IllegalStateException("Cannot set address")), failing("ipv4", failure)) { calls += "refused" }
        })
        assertEquals(listOf("first", "refused", "ipv4"), calls)
    }

    /**
     * The DNS servers [addVpnDnsServers] adds, and the ones it skips, through a stand-in for
     * VpnService.Builder.addDnsServer that refuses 127.0.0.1, 0.0.0.0, ::1 and ::, as it does.
     */
    private fun dnsServers(servers: List<String>, ipv6: Boolean): Pair<List<String>, List<String>> {
        val added = mutableListOf<String>()
        val skipped = mutableListOf<String>()
        val refusals = mutableMapOf<String, IllegalArgumentException>()
        val returned = addVpnDnsServers(servers, ipv6, { server ->
            if (server in setOf("127.0.0.1", "0.0.0.0", "::1", "::")) {
                throw IllegalArgumentException("Bad address").also { refusals[server] = it }
            }
            added += server
        }) { server, e ->
            // The refusal itself reaches the log.
            assertSame(refusals[server], e)
            skipped += server
        }
        assertEquals(added, returned)
        return added to skipped
    }

    @Test
    fun `an interface without IPv6 takes no IPv6 DNS server`() {
        val servers = listOf("8.8.8.8", "2001:4860:4860::8888", "dns.google")

        // With IPv6: every address.
        assertEquals(listOf("8.8.8.8", "2001:4860:4860::8888"), dnsServers(servers, ipv6 = true).first)
        // Without, turned off or refused: an IPv6 one would leave the VPN's IPv6 unblocked.
        assertEquals(listOf("8.8.8.8"), dnsServers(servers, ipv6 = false).first)
        // With none left, the default VPN DNS rather than the default network's.
        assertEquals(listOf("8.8.8.8"), dnsServers(listOf("2001:4860:4860::8888"), ipv6 = false).first)
        assertEquals(listOf("8.8.8.8"), dnsServers(listOf("[2001:4860:4860::8888]"), ipv6 = false).first)
        assertEquals(listOf("8.8.8.8"), dnsServers(emptyList(), ipv6 = false).first)
        assertEquals(listOf("1.1.1.1"), dnsServers(listOf("1.1.1.1", "2606:4700:4700::1111"), ipv6 = false).first)
        // With IPv6 and none given, none, as before; given ones that leave none, a host name too, take the default.
        assertEquals(emptyList<String>(), dnsServers(emptyList(), ipv6 = true).first)
        assertEquals(listOf("8.8.8.8"), dnsServers(listOf("dns.google"), ipv6 = true).first)
    }

    @Test
    fun `a DNS server Android refuses is skipped rather than ending the start`() {
        assertEquals(listOf("1.1.1.1") to listOf("127.0.0.1", "0.0.0.0"), dnsServers(listOf("127.0.0.1", "1.1.1.1", "0.0.0.0"), ipv6 = true))
        assertEquals(listOf("2001:4860:4860::8888") to listOf("::1", "::"), dnsServers(listOf("::1", "::", "2001:4860:4860::8888"), ipv6 = true))
        // With none left, the default VPN DNS rather than the default network's, with IPv6 too.
        assertEquals(listOf("8.8.8.8") to listOf("127.0.0.1"), dnsServers(listOf("127.0.0.1"), ipv6 = true))
        assertEquals(listOf("8.8.8.8") to listOf("0.0.0.0"), dnsServers(listOf("0.0.0.0", "::1"), ipv6 = false))
    }
}
