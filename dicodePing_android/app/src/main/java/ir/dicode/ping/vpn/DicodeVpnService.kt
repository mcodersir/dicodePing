package ir.dicode.ping.vpn

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.VpnService
import android.os.Build
import android.os.ParcelFileDescriptor
import androidx.core.app.NotificationCompat
import ir.dicode.ping.MainActivity
import ir.dicode.ping.R
import ir.dicode.ping.util.AppLog
import ir.dicode.ping.xray.CoreBridge
import ir.dicode.ping.xray.XrayConfigBuilder
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

class DicodeVpnService : VpnService() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var tun: ParcelFileDescriptor? = null
    private var core: CoreBridge? = null
    private var startJob: Job? = null
    private var metricsJob: Job? = null
    private var uploadTotal = 0L
    private var downloadTotal = 0L
    private var currentName = ""
    private var underlyingCallbackRegistered = false
    private var currentUnderlyingNetwork: Network? = null
    private val startGeneration = AtomicLong(0L)

    private val underlyingRequest = NetworkRequest.Builder()
        .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
        .addCapability(NetworkCapabilities.NET_CAPABILITY_NOT_RESTRICTED)
        .addCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)
        .build()

    private val connectivity by lazy { getSystemService(ConnectivityManager::class.java) }
    private val underlyingCallback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) {
            applyUnderlyingNetwork(network, connectivity.getNetworkCapabilities(network))
        }

        override fun onCapabilitiesChanged(network: Network, networkCapabilities: NetworkCapabilities) {
            applyUnderlyingNetwork(network, networkCapabilities)
        }

        override fun onLost(network: Network) {
            if (currentUnderlyingNetwork != network) return
            currentUnderlyingNetwork = null
            scope.launch {
                delay(350)
                val replacement = findBestUnderlyingNetwork()
                if (replacement != null) {
                    applyUnderlyingNetwork(replacement, connectivity.getNetworkCapabilities(replacement))
                } else {
                    setUnderlyingNetworks(null)
                    AppLog.w("VPN", "Underlying network is temporarily unavailable")
                }
            }
        }
    }

    override fun onCreate() {
        super.onCreate()
        createChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopVpn()
            return START_NOT_STICKY
        }

        val raw = intent?.getStringExtra(EXTRA_CONFIG).orEmpty()
        val serverId = intent?.getStringExtra(EXTRA_SERVER_ID).orEmpty()
        val name = intent?.getStringExtra(EXTRA_NAME).orEmpty()
        val bypassDomains = intent?.getStringExtra(EXTRA_BYPASS_DOMAINS).orEmpty()
        val bypassApps = intent?.getStringArrayListExtra(EXTRA_BYPASS_APPS).orEmpty()
        if (raw.isBlank()) {
            stopSelf()
            return START_NOT_STICKY
        }

        currentName = name
        val generation = startGeneration.incrementAndGet()
        startJob?.cancel()
        AppLog.i("VPN", "Start requested for $name; bypassApps=${bypassApps.size}; generation=$generation")
        startForeground(NOTIFICATION_ID, notification(name, getString(R.string.connecting)))
        VpnStateStore.state.value = VpnState(VpnStatus.CONNECTING, serverId, name, getString(R.string.preparing_vpn))
        startJob = scope.launch { startVpn(raw, serverId, name, bypassDomains, bypassApps, generation) }
        return START_REDELIVER_INTENT
    }

    private suspend fun startVpn(
        raw: String,
        serverId: String,
        name: String,
        bypassDomains: String,
        bypassApps: List<String>,
        generation: Long,
    ) {
        try {
            stopRuntime()
            if (prepare(this) != null) error(getString(R.string.vpn_permission_required))
            registerUnderlyingNetworkCallback()

            val builder = Builder()
                .setSession(name.ifBlank { getString(R.string.app_name) })
                .setMtu(VPN_MTU)
                .addAddress(VPN_IPV4_ADDRESS, VPN_IPV4_PREFIX_LENGTH)
                .addRoute("0.0.0.0", 0)
                // Route IPv6 through the TUN as well. Even when a server has no IPv6
                // egress, failing inside the tunnel is safer than leaking traffic over
                // the device's underlying network.
                .addAddress(VPN_IPV6_ADDRESS, VPN_IPV6_PREFIX_LENGTH)
                .addRoute("::", 0)
                .addDnsServer("1.1.1.1")
                .addDnsServer("8.8.8.8")

            // Keep the native core outside its own TUN. This prevents a routing loop.
            builder.addDisallowedApplication(packageName)
            bypassApps.asSequence()
                .map(String::trim)
                .filter { it.isNotBlank() && it != packageName }
                .distinct()
                .forEach { appPackage ->
                    runCatching { builder.addDisallowedApplication(appPackage) }
                        .onFailure { AppLog.w("VPN", "Cannot bypass app $appPackage: ${it.message}") }
                }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) builder.setMetered(false)

            tun = builder.establish() ?: error(getString(R.string.vpn_establish_failed))
            core = CoreBridge(applicationContext) { _ ->
                if (generation == startGeneration.get() && VpnStateStore.state.value.status == VpnStatus.CONNECTING) {
                    VpnStateStore.state.value = VpnState(
                        VpnStatus.CONNECTING,
                        serverId,
                        name,
                        getString(R.string.starting_connection_core),
                    )
                }
            }
            if (core?.available() != true) error(getString(R.string.core_unavailable))

            core!!.start(XrayConfigBuilder.build(raw, bypassDomains), tun!!.fd)
            if (generation != startGeneration.get()) throw CancellationException("Superseded VPN start")
            VpnStateStore.state.value = VpnState(
                VpnStatus.CONNECTING,
                serverId,
                name,
                getString(R.string.verifying_connection),
            )

            // A running core only proves that the config parsed. Confirm real traffic through it.
            val verifiedPing = verifyProxyConnection() ?: error(PROXY_VALIDATION_ERROR)
            if (generation != startGeneration.get()) throw CancellationException("Superseded VPN start")
            AppLog.i("VPN", "Connection verified for $name in ${verifiedPing}ms")

            uploadTotal = 0L
            downloadTotal = 0L
            VpnStateStore.state.value = VpnState(
                status = VpnStatus.CONNECTED,
                serverId = serverId,
                serverName = name,
                message = getString(R.string.connection_verified),
                pingMs = verifiedPing,
            )
            getSystemService(NotificationManager::class.java)
                .notify(NOTIFICATION_ID, notification(name, getString(R.string.connected)))
            startMetrics(name, verifiedPing, generation)
        } catch (cancelled: CancellationException) {
            AppLog.i("VPN", "Connection start cancelled for $name")
            throw cancelled
        } catch (e: Throwable) {
            if (generation != startGeneration.get()) return
            AppLog.e("VPN", "Connection failed for $name", e)
            val message = publicErrorMessage(e)
            stopRuntime()
            VpnStateStore.state.value = VpnState(VpnStatus.ERROR, serverId, name, message)
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
    }

    private suspend fun verifyProxyConnection(): Long? {
        val waits = longArrayOf(0L, 250L, 650L, 1_200L)
        for (waitMs in waits) {
            if (waitMs > 0) delay(waitMs)
            val measured = core?.measureDelay()
            if (measured != null && measured >= 0) return measured
        }
        return null
    }

    private fun registerUnderlyingNetworkCallback() {
        if (underlyingCallbackRegistered) return
        findBestUnderlyingNetwork()?.let { network ->
            applyUnderlyingNetwork(network, connectivity.getNetworkCapabilities(network))
        }
        runCatching {
            connectivity.requestNetwork(underlyingRequest, underlyingCallback)
            underlyingCallbackRegistered = true
        }.onFailure { AppLog.w("VPN", "Underlying network callback failed: ${it.message}") }
    }

    private fun findBestUnderlyingNetwork(): Network? {
        val network = connectivity.activeNetwork ?: return null
        val capabilities = connectivity.getNetworkCapabilities(network) ?: return null
        return network.takeIf {
            !capabilities.hasTransport(NetworkCapabilities.TRANSPORT_VPN) &&
                capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
        }
    }

    private fun applyUnderlyingNetwork(network: Network, capabilities: NetworkCapabilities?) {
        if (capabilities == null ||
            capabilities.hasTransport(NetworkCapabilities.TRANSPORT_VPN) ||
            !capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
        ) return
        if (currentUnderlyingNetwork == network) return

        currentUnderlyingNetwork = network
        runCatching { setUnderlyingNetworks(arrayOf(network)) }
            .onSuccess { AppLog.i("VPN", "Underlying network updated") }
            .onFailure { AppLog.w("VPN", "Cannot set underlying network: ${it.message}") }
    }

    private fun startMetrics(name: String, initialPing: Long, generation: Long) {
        metricsJob?.cancel()
        metricsJob = scope.launch {
            var ping: Long? = initialPing
            var pingCountdown = 9
            var consecutiveProbeFailures = 0
            while (isActive && generation == startGeneration.get()) {
                val activeCore = core
                if (activeCore?.isRunning() != true) {
                    AppLog.e("VPN", "Core stopped unexpectedly for $name")
                    VpnStateStore.state.value = VpnState(
                        status = VpnStatus.ERROR,
                        serverId = VpnStateStore.state.value.serverId,
                        serverName = name,
                        message = getString(R.string.connection_lost),
                        uploadBytes = uploadTotal,
                        downloadBytes = downloadTotal,
                        pingMs = null,
                    )
                    stopRuntime()
                    stopForeground(STOP_FOREGROUND_REMOVE)
                    stopSelf()
                    return@launch
                }

                val delta = activeCore.queryTrafficDelta()
                uploadTotal += delta.first
                downloadTotal += delta.second
                if (pingCountdown <= 0) {
                    val checked = activeCore.measureDelay()
                    if (checked == null) {
                        consecutiveProbeFailures++
                        if (consecutiveProbeFailures >= 3) ping = null
                    } else {
                        ping = checked
                        consecutiveProbeFailures = 0
                    }
                    pingCountdown = 9
                } else {
                    pingCountdown--
                }

                // Do not tear down a working tunnel just because a public probe endpoint is
                // temporarily blocked. The core state and real traffic remain authoritative.
                VpnStateStore.state.value = VpnState(
                    status = VpnStatus.CONNECTED,
                    serverId = VpnStateStore.state.value.serverId,
                    serverName = name,
                    message = getString(R.string.connection_verified),
                    uploadBytes = uploadTotal,
                    downloadBytes = downloadTotal,
                    pingMs = ping,
                )
                delay(3_000)
            }
        }
    }

    private fun notification(name: String, status: String) = NotificationCompat.Builder(this, CHANNEL_ID)
        .setSmallIcon(R.drawable.ic_bolt)
        .setContentTitle(getString(R.string.app_name))
        .setContentText("$status • $name")
        .setOngoing(true)
        .setOnlyAlertOnce(true)
        .setContentIntent(
            PendingIntent.getActivity(
                this,
                1,
                Intent(this, MainActivity::class.java),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            )
        )
        .addAction(
            0,
            getString(R.string.disconnect),
            PendingIntent.getService(
                this,
                2,
                Intent(this, DicodeVpnService::class.java).setAction(ACTION_STOP),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            ),
        )
        .build()

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            getSystemService(NotificationManager::class.java).createNotificationChannel(
                NotificationChannel(CHANNEL_ID, getString(R.string.vpn_channel), NotificationManager.IMPORTANCE_LOW)
            )
        }
    }

    private fun stopRuntime() {
        metricsJob?.cancel()
        metricsJob = null
        runCatching { core?.stop() }
        core = null
        runCatching { tun?.close() }
        tun = null
        if (underlyingCallbackRegistered) {
            runCatching { connectivity.unregisterNetworkCallback(underlyingCallback) }
            underlyingCallbackRegistered = false
        }
        currentUnderlyingNetwork = null
        runCatching { setUnderlyingNetworks(null) }
    }

    private fun stopVpn() {
        AppLog.i("VPN", "Stop requested for $currentName")
        startGeneration.incrementAndGet()
        startJob?.cancel()
        startJob = null
        stopRuntime()
        VpnStateStore.state.value = VpnState()
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun unwrapMessage(error: Throwable): String {
        var current: Throwable? = error
        var last = error.message.orEmpty()
        repeat(6) {
            if (current == null) return@repeat
            if (!current?.message.isNullOrBlank()) last = current?.message.orEmpty()
            current = current?.cause
        }
        return last.ifBlank { error.javaClass.simpleName }
    }

    private fun publicErrorMessage(error: Throwable): String {
        val raw = unwrapMessage(error)
        return when {
            raw.contains(PROXY_VALIDATION_ERROR, ignoreCase = true) -> getString(R.string.server_unreachable)
            raw.contains("permission", ignoreCase = true) -> getString(R.string.vpn_permission_required)
            raw.contains("establish", ignoreCase = true) -> getString(R.string.vpn_establish_failed)
            raw.contains("core", ignoreCase = true) ||
                raw.contains("ClassNotFound", ignoreCase = true) ||
                raw.contains("libv2ray", ignoreCase = true) -> getString(R.string.core_unavailable)
            raw.contains("unsupported", ignoreCase = true) ||
                raw.contains("invalid configuration", ignoreCase = true) -> getString(R.string.invalid_server_config)
            else -> getString(R.string.connection_failed_retry)
        }
    }

    override fun onRevoke() {
        AppLog.w("VPN", "VPN permission was revoked by the system")
        stopVpn()
        super.onRevoke()
    }

    override fun onDestroy() {
        startGeneration.incrementAndGet()
        startJob?.cancel()
        stopRuntime()
        scope.cancel()
        super.onDestroy()
    }

    companion object {
        const val ACTION_STOP = "ir.dicode.ping.STOP"
        const val EXTRA_CONFIG = "config"
        const val EXTRA_SERVER_ID = "server_id"
        const val EXTRA_NAME = "name"
        const val EXTRA_BYPASS_DOMAINS = "bypass_domains"
        const val EXTRA_BYPASS_APPS = "bypass_apps"
        private const val CHANNEL_ID = "dicodeping_vpn"
        private const val NOTIFICATION_ID = 7101
        private const val PROXY_VALIDATION_ERROR = "proxy validation failed"
        private const val VPN_MTU = 1400
        private const val VPN_IPV4_ADDRESS = "172.19.0.1"
        private const val VPN_IPV4_PREFIX_LENGTH = 30
        private const val VPN_IPV6_ADDRESS = "fdfe:dcba:9876::1"
        private const val VPN_IPV6_PREFIX_LENGTH = 126
    }
}
