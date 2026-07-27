package ir.dicode.ping.vpn

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.VpnService
import android.os.Build
import android.os.ParcelFileDescriptor
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import ir.dicode.ping.MainActivity
import ir.dicode.ping.R
import ir.dicode.ping.util.AppLog
import ir.dicode.ping.xray.CoreBridge
import ir.dicode.ping.xray.XrayConfigBuilder
import ir.dicode.ping.data.SettingsStore
import ir.dicode.ping.core.AndroidExternalCoreProcess
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicBoolean
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

class DicodeVpnService : VpnService() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var tun: ParcelFileDescriptor? = null
    private var core: CoreBridge? = null
    private var externalCore: AndroidExternalCoreProcess? = null
    private var startJob: Job? = null
    private var metricsJob: Job? = null
    private var uploadTotal = 0L
    private var downloadTotal = 0L
    private var currentName = ""
    private var currentSharingError = ""
    private var underlyingCallbackRegistered = false
    private var currentUnderlyingNetwork: Network? = null
    private val startGeneration = AtomicLong(0L)
    private val runtimeMutex = Mutex()
    private val stopping = AtomicBoolean(false)
    private val tetheringController = AndroidTetheringController()

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
        val coreId = intent?.getStringExtra(EXTRA_CORE_ID).orEmpty().ifBlank { "xray" }
        val serverId = intent?.getStringExtra(EXTRA_SERVER_ID).orEmpty()
        val name = intent?.getStringExtra(EXTRA_NAME).orEmpty()
        val bypassDomains = intent?.getStringExtra(EXTRA_BYPASS_DOMAINS).orEmpty()
        val bypassApps = intent?.getStringArrayListExtra(EXTRA_BYPASS_APPS).orEmpty()
        val perAppMode = intent?.getStringExtra(EXTRA_PER_APP_MODE) ?: "disabled"
        val perAppPackages = intent?.getStringArrayListExtra(EXTRA_PER_APP_PACKAGES).orEmpty()
        val vpnSharingUsb = intent?.getBooleanExtra(EXTRA_VPN_SHARING_USB, false) ?: false
        val vpnSharingHotspot = intent?.getBooleanExtra(EXTRA_VPN_SHARING_HOTSPOT, false) ?: false
        if (raw.isBlank() && coreId == "xray") {
            VpnStateStore.state.value = VpnState(
                VpnStatus.ERROR,
                serverId,
                name,
                getString(R.string.invalid_server_config),
            )
            stopSelf()
            return START_NOT_STICKY
        }

        currentName = name
        stopping.set(false)
        val generation = startGeneration.incrementAndGet()
        val previousStart = startJob
        AppLog.i("VPN", "Start requested for $name; bypassApps=${bypassApps.size}; perAppMode=$perAppMode; perAppPackages=${perAppPackages.size}; sharingUsb=$vpnSharingUsb; sharingHotspot=$vpnSharingHotspot; generation=$generation")
        val foregroundType = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
        } else {
            0
        }
        ServiceCompat.startForeground(
            this,
            NOTIFICATION_ID,
            notification(name, getString(R.string.connecting)),
            foregroundType,
        )
        VpnStateStore.state.value = VpnState(VpnStatus.CONNECTING, serverId, name, getString(R.string.preparing_vpn))
        startJob = scope.launch {
            previousStart?.cancelAndJoin()
            runtimeMutex.withLock {
                startVpn(raw, coreId, serverId, name, bypassDomains, bypassApps, perAppMode, perAppPackages, vpnSharingUsb, vpnSharingHotspot, generation)
            }
        }
        // Never replay an old server/config after Android recreates the service.
        // The UI or scanner state machine must issue an explicit fresh request.
        return START_NOT_STICKY
    }

    private suspend fun startVpn(
        raw: String,
        coreId: String,
        serverId: String,
        name: String,
        bypassDomains: String,
        bypassApps: List<String>,
        perAppMode: String,
        perAppPackages: List<String>,
        vpnSharingUsb: Boolean,
        vpnSharingHotspot: Boolean,
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
                // Keep DNS inside the verified proxy path. Using the underlying
                // network's resolver here can route private ISP DNS into the TUN
                // and leave the app "connected" while every hostname fails.
                .addDnsServer("1.1.1.1")
                .addDnsServer("8.8.8.8")

            // v1.7.0-rc.2: Per-app VPN support.
            // Three modes:
            //   "disabled"  — all apps use VPN (default; bypass apps still apply)
            //   "allowlist" — only perAppPackages use VPN
            //   "denylist"  — perAppPackages do NOT use VPN (same as bypass apps)
            when (perAppMode) {
                "allowlist" -> {
                    // Only selected apps go through VPN.
                    // The native core must always be allowed to prevent a routing loop.
                    perAppPackages.asSequence()
                        .map(String::trim)
                        .filter { it.isNotBlank() }
                        .distinct()
                        .forEach { appPackage ->
                            runCatching { builder.addAllowedApplication(appPackage) }
                                .onFailure { AppLog.w("VPN", "Cannot allow app $appPackage: ${it.message}") }
                        }
                    // Xray protects its sockets itself. External bundled cores must
                    // stay outside the TUN to avoid a same-UID routing loop.
                    if (coreId == "xray") runCatching { builder.addAllowedApplication(packageName) }
                    AppLog.i("VPN", "Per-app VPN: allowlist mode with ${perAppPackages.size} apps")
                }
                "denylist" -> {
                    // Selected apps bypass VPN.
                    builder.addDisallowedApplication(packageName)
                    perAppPackages.asSequence()
                        .map(String::trim)
                        .filter { it.isNotBlank() && it != packageName }
                        .distinct()
                        .forEach { appPackage ->
                            runCatching { builder.addDisallowedApplication(appPackage) }
                                .onFailure { AppLog.w("VPN", "Cannot disallow app $appPackage: ${it.message}") }
                        }
                    AppLog.i("VPN", "Per-app VPN: denylist mode with ${perAppPackages.size} apps")
                }
                else -> {
                    // "disabled" — all apps use VPN, bypass apps still apply.
                    builder.addDisallowedApplication(packageName)
                    bypassApps.asSequence()
                        .map(String::trim)
                        .filter { it.isNotBlank() && it != packageName }
                        .distinct()
                        .forEach { appPackage ->
                            runCatching { builder.addDisallowedApplication(appPackage) }
                                .onFailure { AppLog.w("VPN", "Cannot bypass app $appPackage: ${it.message}") }
                        }
                }
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

            val resources = ir.dicode.ping.util.RuntimeTuning.detect(applicationContext)
            val settings = SettingsStore(applicationContext)
            val xrayConfig = if (coreId == "xray") {
                XrayConfigBuilder.build(
                    raw,
                    bypassDomains,
                    resources.bufferSizeKiB,
                    settings.cdnFormattingDomain.takeIf { settings.cdnFormattingEnabled }.orEmpty(),
                    settings.secureDnsDoh,
                )
            } else {
                check(coreId == "aether" || coreId == "warp") { "Unsupported bundled core: $coreId" }
                val helper = AndroidExternalCoreProcess(applicationContext, coreId)
                helper.start(settings.warpTermsAccepted)
                externalCore = helper
                XrayConfigBuilder.buildSocksBridge(
                    helper.socksPort,
                    resources.bufferSizeKiB,
                    settings.secureDnsDoh,
                )
            }
            core!!.start(xrayConfig, tun!!.fd)
            if (generation != startGeneration.get()) throw CancellationException("Superseded VPN start")
            VpnStateStore.state.value = VpnState(
                VpnStatus.CONNECTING,
                serverId,
                name,
                getString(R.string.verifying_connection),
            )

            // A running core only proves that the config parsed. Confirm real traffic through it.
            val verifiedPing = verifyProxyConnection() ?: error(PROXY_VALIDATION_ERROR)
            if (core?.isRunning() != true) error("Xray stopped immediately after connection verification")
            if (generation != startGeneration.get()) throw CancellationException("Superseded VPN start")
            AppLog.i("VPN", "Connection verified for $name in ${verifiedPing}ms")
            currentSharingError = if (vpnSharingUsb || vpnSharingHotspot) {
                tetheringController.start(vpnSharingUsb, vpnSharingHotspot)
                    .exceptionOrNull()?.message.orEmpty()
            } else ""

            uploadTotal = 0L
            downloadTotal = 0L
            VpnStateStore.state.value = VpnState(
                status = VpnStatus.CONNECTED,
                serverId = serverId,
                serverName = name,
                message = if (currentSharingError.isBlank()) {
                    getString(R.string.connection_verified)
                } else {
                    getString(R.string.vpn_sharing_unavailable)
                },
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
                if (activeCore?.isRunning() != true || externalCore?.let { !it.isRunning() } == true) {
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
                    message = if (currentSharingError.isBlank()) {
                        getString(R.string.connection_verified)
                    } else {
                        getString(R.string.vpn_sharing_unavailable)
                    },
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

    @Synchronized
    private fun stopRuntime() {
        tetheringController.stop()
        currentSharingError = ""
        metricsJob?.cancel()
        metricsJob = null
        runCatching { core?.stop() }
        core = null
        runCatching { externalCore?.stop() }
        externalCore = null
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
        if (!stopping.compareAndSet(false, true)) return
        AppLog.i("VPN", "Stop requested for $currentName")
        startGeneration.incrementAndGet()
        val previousStart = startJob
        // Keep the foreground service alive until native cleanup finishes. This
        // prevents Android from killing the process while libgojni is shutting down.
        startJob = scope.launch {
            try {
                previousStart?.cancelAndJoin()
                runtimeMutex.withLock { stopRuntime() }
                VpnStateStore.state.value = VpnState()
                currentName = ""
            } finally {
                stopping.set(false)
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
            }
        }
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
        // Android may invoke onRevoke off the main thread. The platform's
        // default implementation calls stopSelf() immediately, which can race
        // our native Xray/TUN cleanup. Let the serialized stop transaction own
        // service termination after all handles are closed.
        runCatching { stopVpn() }
            .onFailure { error ->
                AppLog.e("VPN", "Graceful revoke cleanup failed", error)
                VpnStateStore.state.value = VpnState()
                stopSelf()
            }
    }

    override fun onDestroy() {
        startGeneration.incrementAndGet()
        startJob?.cancel()
        metricsJob?.cancel()
        // Never wait for native shutdown on Android's service main thread.
        // Close the TUN immediately, detach the handles, and stop helpers on IO.
        val detachedTun = tun.also { tun = null }
        val detachedCore = core.also { core = null }
        val detachedExternal = externalCore.also { externalCore = null }
        runCatching { detachedTun?.close() }
        CoroutineScope(SupervisorJob() + Dispatchers.IO).launch {
            runCatching { detachedCore?.stop() }
            runCatching { detachedExternal?.stop() }
        }
        scope.cancel()
        // A destroyed service must never leave the UI or scanner waiting forever in CONNECTING.
        if (VpnStateStore.state.value.status != VpnStatus.DISCONNECTED) {
            VpnStateStore.state.value = VpnState()
        }
        super.onDestroy()
    }

    companion object {
        const val ACTION_STOP = "ir.dicode.ping.STOP"
        const val EXTRA_CONFIG = "config"
        const val EXTRA_CORE_ID = "core_id"
        const val EXTRA_SERVER_ID = "server_id"
        const val EXTRA_NAME = "name"
        const val EXTRA_BYPASS_DOMAINS = "bypass_domains"
        const val EXTRA_BYPASS_APPS = "bypass_apps"
        const val EXTRA_PER_APP_MODE = "per_app_mode"
        const val EXTRA_PER_APP_PACKAGES = "per_app_packages"
        const val EXTRA_VPN_SHARING_USB = "vpn_sharing_usb"
        const val EXTRA_VPN_SHARING_HOTSPOT = "vpn_sharing_hotspot"
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
