package ir.dicode.ping.vpn

import ir.dicode.ping.util.AppLog
import java.net.NetworkInterface

/**
 * Routes tethered clients into the VpnService TUN on rooted/system builds.
 * Stock Android does not expose forwarded tether traffic to ordinary
 * VpnService applications, so failure is explicit rather than cosmetic.
 */
class AndroidTetheringController {
    private var active = false

    fun start(usb: Boolean, hotspot: Boolean): Result<Unit> = runCatching {
        if (!usb && !hotspot) return@runCatching
        require(hasRoot()) { "VPN sharing requires root/system privileges on Android" }
        val tun = findTun() ?: error("VPN TUN interface was not found")
        if (usb) root("svc usb setFunctions rndis,adb")
        if (hotspot) root("cmd connectivity tether start wifi")

        root("iptables -t mangle -N DICODEPING_SHARE 2>/dev/null || true")
        root("iptables -t mangle -F DICODEPING_SHARE")
        if (usb) root("iptables -t mangle -A DICODEPING_SHARE -i rndis+ -j MARK --set-mark 0xd1c0")
        if (hotspot) {
            root("iptables -t mangle -A DICODEPING_SHARE -i wlan+ -j MARK --set-mark 0xd1c0")
            root("iptables -t mangle -A DICODEPING_SHARE -i ap+ -j MARK --set-mark 0xd1c0")
        }
        root("iptables -t mangle -C PREROUTING -j DICODEPING_SHARE 2>/dev/null || " +
            "iptables -t mangle -I PREROUTING 1 -j DICODEPING_SHARE")
        root("ip rule add fwmark 0xd1c0 lookup 18180 priority 11818 2>/dev/null || true")
        root("ip route replace default dev $tun table 18180")
        active = true
        AppLog.i("Sharing", "Android tether traffic routed to $tun")
    }.onFailure {
        AppLog.w("Sharing", "Android VPN sharing unavailable: ${it.message}")
        stop()
    }

    fun stop() {
        if (!active && !hasRoot()) return
        runCatching { root("ip rule del fwmark 0xd1c0 lookup 18180 priority 11818 2>/dev/null || true") }
        runCatching { root("ip route flush table 18180 2>/dev/null || true") }
        runCatching { root("iptables -t mangle -D PREROUTING -j DICODEPING_SHARE 2>/dev/null || true") }
        runCatching { root("iptables -t mangle -F DICODEPING_SHARE 2>/dev/null || true") }
        runCatching { root("iptables -t mangle -X DICODEPING_SHARE 2>/dev/null || true") }
        active = false
    }

    private fun hasRoot(): Boolean = runCatching {
        ProcessBuilder("su", "-c", "id -u").start().let { process ->
            process.waitFor() == 0 && process.inputStream.bufferedReader().readText().trim() == "0"
        }
    }.getOrDefault(false)

    private fun root(command: String) {
        val process = ProcessBuilder("su", "-c", command)
            .redirectErrorStream(true)
            .start()
        val output = process.inputStream.bufferedReader().readText()
        check(process.waitFor() == 0) { output.ifBlank { "Root command failed" } }
    }

    private fun findTun(): String? = NetworkInterface.getNetworkInterfaces().toList()
        .firstOrNull { network ->
            network.inetAddresses.toList().any { it.hostAddress?.substringBefore('%') == "172.19.0.1" }
        }?.name
}
