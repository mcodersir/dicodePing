package ir.dicode.ping.vpn

import kotlinx.coroutines.flow.MutableStateFlow

enum class VpnStatus { DISCONNECTED, CONNECTING, CONNECTED, ERROR }

data class VpnState(
    val status: VpnStatus = VpnStatus.DISCONNECTED,
    val serverId: String = "",
    val serverName: String = "",
    val message: String = "",
    val uploadBytes: Long = 0L,
    val downloadBytes: Long = 0L,
    val pingMs: Long? = null,
)

object VpnStateStore {
    val state = MutableStateFlow(VpnState())
}
