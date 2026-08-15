package ir.dicode.ping

import android.Manifest
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.content.res.Configuration
import android.net.VpnService
import android.os.Build
import android.os.Bundle
import androidx.activity.SystemBarStyle
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.core.view.updatePadding
import androidx.fragment.app.Fragment
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import ir.dicode.ping.data.ServerRecord
import ir.dicode.ping.data.ServerPolicy
import ir.dicode.ping.data.SettingsStore
import ir.dicode.ping.databinding.ActivityMainBinding
import ir.dicode.ping.ui.AboutFragment
import ir.dicode.ping.ui.MainViewModel
import ir.dicode.ping.ui.ScannerFragment
import ir.dicode.ping.scanner.ScannerCoordinator
import ir.dicode.ping.scanner.ScannerService
import ir.dicode.ping.ui.ServersFragment
import ir.dicode.ping.ui.SettingsFragment
import ir.dicode.ping.util.AppLog
import ir.dicode.ping.util.LocaleHelper
import ir.dicode.ping.util.PublicServerLabel
import ir.dicode.ping.vpn.DicodeVpnService
import ir.dicode.ping.vpn.VpnState
import ir.dicode.ping.vpn.VpnStateStore
import ir.dicode.ping.vpn.VpnStatus
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity(), ConnectionHost {
    private lateinit var binding: ActivityMainBinding
    private val vm: MainViewModel by viewModels()
    private var pendingServer: ServerRecord? = null
    private var currentPageId = 0
    private val automaticQueue = ArrayDeque<ServerRecord>()
    private var automaticAttemptId = ""
    private var automaticRetryScheduled = false
    private var pendingScannerStart = false
    private var scannerLaunchScheduled = false

    private val vpnPermission = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val server = pendingServer ?: return@registerForActivityResult
        pendingServer = null

        lifecycleScope.launch {
            if (result.resultCode != RESULT_OK) {
                VpnStateStore.state.value = VpnState(
                    status = VpnStatus.ERROR,
                    serverId = server.id,
                    serverName = server.name,
                    message = getString(R.string.vpn_permission_failed_message),
                )
                if (pendingScannerStart) {
                    failPendingScannerConnection(getString(R.string.vpn_permission_failed_message))
                } else {
                    showVpnPermissionError()
                }
                return@launch
            }
            var granted = false
            for (attempt in 0 until 4) {
                delay(250)
                granted = runCatching { VpnService.prepare(this@MainActivity) == null }.getOrDefault(false)
                if (granted) break
            }
            if (granted) startVpn(server) else {
                VpnStateStore.state.value = VpnState(
                    status = VpnStatus.ERROR,
                    serverId = server.id,
                    serverName = server.name,
                    message = getString(R.string.vpn_permission_failed_message),
                )
                if (pendingScannerStart) {
                    failPendingScannerConnection(getString(R.string.vpn_permission_failed_message))
                } else {
                    showVpnPermissionError()
                }
            }
        }
    }

    private val notificationPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    override fun attachBaseContext(newBase: Context) {
        super.attachBaseContext(LocaleHelper.wrap(newBase, SettingsStore(newBase).language))
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.auto(Color.TRANSPARENT, Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.auto(Color.TRANSPARENT, Color.TRANSPARENT),
        )
        super.onCreate(savedInstanceState)

        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        configureSystemBars()
        applySystemBarInsets()

        binding.mainToolbar.setOnMenuItemClickListener { item ->
            when (item.itemId) {
                R.id.nav_servers -> showPage(R.id.nav_servers)
                R.id.nav_scanner -> requestScannerLaunch()
                R.id.nav_settings -> showPage(R.id.nav_settings)
                R.id.nav_about -> showPage(R.id.nav_about)
                else -> return@setOnMenuItemClickListener false
            }
            true
        }
        binding.connectFab.setOnClickListener {
            when (VpnStateStore.state.value.status) {
                VpnStatus.CONNECTED, VpnStatus.CONNECTING -> disconnect()
                else -> connect(null)
            }
        }
        updateConnectionChrome(VpnStateStore.state.value)

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (currentPageId != R.id.nav_servers) {
                    showPage(R.id.nav_servers)
                } else {
                    finish()
                }
            }
        })

        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED
        ) {
            notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }

        val restoredPage = savedInstanceState?.getInt(KEY_CURRENT_PAGE, R.id.nav_servers) ?: R.id.nav_servers
        pendingScannerStart = savedInstanceState?.getBoolean(KEY_PENDING_SCANNER, false) ?: false
        currentPageId = 0
        showPage(restoredPage, animate = false)

        lifecycleScope.launch {
            VpnStateStore.state.collect { state ->
                updateConnectionChrome(state)
                when {
                    state.status == VpnStatus.CONNECTED -> {
                        if (state.serverId == automaticAttemptId) clearAutomaticQueue()
                        if (pendingScannerStart) launchScannerAfterConnection()
                    }
                    state.status == VpnStatus.ERROR &&
                        state.serverId == automaticAttemptId &&
                        automaticAttemptId.isNotBlank() &&
                        !automaticRetryScheduled -> retryAutomaticConnection()
                    state.status == VpnStatus.ERROR &&
                        pendingScannerStart &&
                        automaticAttemptId.isBlank() -> failPendingScannerConnection(
                            state.message.ifBlank { getString(R.string.connection_failed_retry) },
                        )
                }
            }
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        outState.putInt(KEY_CURRENT_PAGE, currentPageId.takeIf { it != 0 } ?: R.id.nav_servers)
        outState.putBoolean(KEY_PENDING_SCANNER, pendingScannerStart)
        super.onSaveInstanceState(outState)
    }

    private fun configureSystemBars() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            window.isNavigationBarContrastEnforced = false
        }
        val isNight = resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK ==
            Configuration.UI_MODE_NIGHT_YES
        WindowInsetsControllerCompat(window, binding.root).apply {
            isAppearanceLightStatusBars = !isNight
            isAppearanceLightNavigationBars = !isNight
        }
    }

    private fun applySystemBarInsets() {
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { _, windowInsets ->
            val statusAndCutout = windowInsets.getInsets(
                WindowInsetsCompat.Type.statusBars() or WindowInsetsCompat.Type.displayCutout(),
            )
            val navigation = windowInsets.getInsets(WindowInsetsCompat.Type.navigationBars())

            binding.mainToolbar.updatePadding(
                left = statusAndCutout.left,
                top = statusAndCutout.top,
                right = statusAndCutout.right,
            )
            binding.fragmentHost.updatePadding(left = statusAndCutout.left, right = statusAndCutout.right)
            val fabParams = binding.connectFab.layoutParams as android.view.ViewGroup.MarginLayoutParams
            fabParams.bottomMargin = navigation.bottom + (20 * resources.displayMetrics.density).toInt()
            fabParams.rightMargin = navigation.right + (20 * resources.displayMetrics.density).toInt()
            fabParams.leftMargin = navigation.left + (20 * resources.displayMetrics.density).toInt()
            binding.connectFab.layoutParams = fabParams
            windowInsets
        }
        ViewCompat.requestApplyInsets(binding.root)
    }

    private fun showPage(id: Int, animate: Boolean = true) {
        val pageId = id
        val tag = pageTag(pageId)
        val existing = supportFragmentManager.findFragmentByTag(tag)
        if (pageId == currentPageId && existing?.isVisible == true) return

        AppLog.i("Navigation", "Open destination=$pageId")
        currentPageId = pageId
        val target = existing ?: createPage(pageId)
        val transaction = supportFragmentManager.beginTransaction().setReorderingAllowed(true)
        if (animate) {
            transaction.setCustomAnimations(android.R.anim.fade_in, android.R.anim.fade_out)
        }

        supportFragmentManager.fragments.forEach { fragment ->
            if (fragment.isAdded && fragment !== target) {
                transaction.hide(fragment)
                transaction.setMaxLifecycle(fragment, Lifecycle.State.STARTED)
            }
        }
        if (target.isAdded) transaction.show(target) else transaction.add(R.id.fragmentHost, target, tag)
        transaction.setMaxLifecycle(target, Lifecycle.State.RESUMED)
        transaction.setPrimaryNavigationFragment(target)
        transaction.commit()
        binding.mainToolbar.title = when (pageId) {
            R.id.nav_settings -> getString(R.string.nav_settings)
            R.id.nav_scanner -> getString(R.string.nav_scanner)
            R.id.nav_about -> getString(R.string.nav_about)
            else -> getString(R.string.app_name)
        }
    }

    private fun createPage(id: Int): Fragment = when (id) {
        R.id.nav_servers -> ServersFragment()
        R.id.nav_scanner -> ScannerFragment()
        R.id.nav_settings -> SettingsFragment()
        R.id.nav_about -> AboutFragment()
        else -> ServersFragment()
    }

    private fun pageTag(id: Int): String = "main_page_$id"

    private fun updateConnectionChrome(state: VpnState) {
        val active = state.status == VpnStatus.CONNECTED || state.status == VpnStatus.CONNECTING
        binding.connectFab.setImageResource(if (active) R.drawable.ic_power else R.drawable.ic_bolt)
        binding.connectFab.contentDescription = getString(if (active) R.string.disconnect else R.string.connect)
        binding.mainToolbar.subtitle = when (state.status) {
            VpnStatus.CONNECTED -> getString(R.string.connected)
            VpnStatus.CONNECTING -> getString(R.string.connecting)
            VpnStatus.ERROR -> getString(R.string.connection_error)
            else -> getString(R.string.ready_to_connect)
        }
    }

    override fun requestScannerLaunch() {
        if (isFinishing || isDestroyed) return
        val coordinator = ScannerCoordinator.get(applicationContext)
        if (coordinator.state.value.running) {
            showPage(R.id.nav_scanner)
            return
        }
        val settings = vm.repo.settings
        if (!settings.scannerVpnNoticeSeen) {
            // Persist the one-time flag only after Android successfully displays
            // the dialog. A lifecycle race must not silently consume the notice.
            runCatching {
                MaterialAlertDialogBuilder(this)
                    .setTitle(R.string.scanner_vpn_notice_title)
                    .setMessage(R.string.scanner_vpn_notice_message)
                    .setNegativeButton(R.string.later, null)
                    .setPositiveButton(R.string.scanner_go_home_connect) { _, _ -> continueScannerLaunch() }
                    .show()
            }.onSuccess {
                settings.scannerVpnNoticeSeen = true
            }.onFailure { error ->
                AppLog.e("ScannerLaunch", "Cannot show scanner VPN notice", error)
            }
            return
        }
        continueScannerLaunch()
    }

    private fun continueScannerLaunch() {
        if (isFinishing || isDestroyed) return
        pendingScannerStart = true
        scannerLaunchScheduled = false
        // The scanner uses the app-owned runtime connection so it can stop it
        // deterministically before probing the collected configs.
        showPage(R.id.nav_servers)
        when (VpnStateStore.state.value.status) {
            VpnStatus.CONNECTED -> launchScannerAfterConnection()
            VpnStatus.CONNECTING -> Unit
            else -> connect(null)
        }
    }

    private fun launchScannerAfterConnection() {
        if (!pendingScannerStart || scannerLaunchScheduled || isFinishing || isDestroyed) return
        if (VpnStateStore.state.value.status != VpnStatus.CONNECTED) return
        scannerLaunchScheduled = true
        // Keep the pending flag until startForegroundService succeeds. This
        // lets a recreated Activity resume the transaction after rotation.
        showPage(R.id.nav_scanner)
        lifecycleScope.launch {
            delay(180)
            if (isFinishing || isDestroyed) return@launch
            if (VpnStateStore.state.value.status != VpnStatus.CONNECTED) {
                scannerLaunchScheduled = false
                failPendingScannerConnection(getString(R.string.connection_failed_retry))
                return@launch
            }
            runCatching {
                ContextCompat.startForegroundService(
                    applicationContext,
                    Intent(applicationContext, ScannerService::class.java)
                        .putExtra(ScannerService.EXTRA_NAME, "SUB"),
                )
            }.onSuccess {
                pendingScannerStart = false
                scannerLaunchScheduled = false
            }.onFailure { error ->
                scannerLaunchScheduled = false
                AppLog.e("ScannerLaunch", "Cannot start scanner service", error)
                failPendingScannerConnection(error.message ?: getString(R.string.scanner_launch_failed))
            }
        }
    }

    private fun failPendingScannerConnection(detail: String) {
        pendingScannerStart = false
        scannerLaunchScheduled = false
        if (isFinishing || isDestroyed) return
        MaterialAlertDialogBuilder(this)
            .setTitle(R.string.scanner_connection_failed_title)
            .setMessage(getString(R.string.scanner_connection_failed_message, detail.take(240)))
            .setPositiveButton(android.R.string.ok, null)
            .show()
    }

    override fun connect(server: ServerRecord?) {
        // Startup ping refresh must never make the Connect button inert.  The
        // saved candidate pool is available immediately and each candidate is
        // still accepted only after DicodeVpnService passes a real HTTP probe.
        if (server == null && vm.repo.connectionMode.value == "auto") {
            val candidates = vm.repo.connectionCandidates(AUTO_RETRY_LIMIT)
            if (candidates.isNotEmpty()) {
                clearAutomaticQueue()
                automaticQueue.addAll(candidates.drop(1))
                automaticAttemptId = candidates.first().id
                prepareAndStart(candidates.first())
                return
            }
        }

        val candidate = server ?: vm.repo.connectionTarget()
        if (candidate == null) {
            if (pendingScannerStart) {
                failPendingScannerConnection(getString(R.string.no_server_message))
            } else {
                MaterialAlertDialogBuilder(this)
                    .setTitle(R.string.no_server_title)
                    .setMessage(R.string.no_server_message)
                    .setPositiveButton(android.R.string.ok, null)
                    .show()
            }
            return
        }
        if (ServerPolicy.isRestricted(candidate)) {
            if (pendingScannerStart) {
                failPendingScannerConnection(getString(R.string.restricted_server_message))
            } else {
                MaterialAlertDialogBuilder(this)
                    .setTitle(R.string.server_disabled)
                    .setMessage(R.string.restricted_server_message)
                    .setPositiveButton(android.R.string.ok, null)
                    .show()
            }
            return
        }

        clearAutomaticQueue()
        prepareAndStart(candidate)
    }

    private fun prepareAndStart(candidate: ServerRecord) {
        vm.repo.selectServer(candidate.id, userInitiated = false)
        VpnStateStore.state.value = VpnState(
            status = VpnStatus.CONNECTING,
            serverId = candidate.id,
            serverName = candidate.name,
            message = getString(R.string.preparing_vpn),
        )
        val prepared = runCatching { VpnService.prepare(this) }
        prepared.onFailure { error ->
            AppLog.e("Main", "VPN preparation failed", error)
            VpnStateStore.state.value = VpnState(
                status = VpnStatus.ERROR,
                serverId = candidate.id,
                serverName = candidate.name,
                message = getString(R.string.connection_failed_retry),
            )
        }
        val prepareIntent = prepared.getOrNull() ?: run {
            if (prepared.isSuccess) startVpn(candidate)
            return
        }
        pendingServer = candidate
        runCatching { vpnPermission.launch(prepareIntent) }
            .onFailure { error ->
                pendingServer = null
                AppLog.e("Main", "Cannot open VPN permission activity", error)
                VpnStateStore.state.value = VpnState(
                    status = VpnStatus.ERROR,
                    serverId = candidate.id,
                    serverName = candidate.name,
                    message = getString(R.string.vpn_permission_failed_message),
                )
            }
    }

    private suspend fun retryAutomaticConnection() {
        automaticRetryScheduled = true
        delay(AUTO_RETRY_DELAY_MS)
        val next = automaticQueue.removeFirstOrNull()
        if (next == null) {
            clearAutomaticQueue()
            if (pendingScannerStart) {
                failPendingScannerConnection(getString(R.string.connection_failed_retry))
            }
        } else {
            automaticAttemptId = next.id
            prepareAndStart(next)
        }
        automaticRetryScheduled = false
    }

    private fun clearAutomaticQueue() {
        automaticQueue.clear()
        automaticAttemptId = ""
        automaticRetryScheduled = false
    }

    private fun startVpn(server: ServerRecord) {
        AppLog.i("Main", "Starting VPN for server=${server.id}")
        val settings = vm.repo.settings
        val intent = Intent(applicationContext, DicodeVpnService::class.java)
            .putExtra(DicodeVpnService.EXTRA_CONFIG, server.raw)
            .putExtra(DicodeVpnService.EXTRA_SERVER_ID, server.id)
            .putExtra(
                DicodeVpnService.EXTRA_NAME,
                PublicServerLabel.name(
                    server.name,
                    server.city.ifBlank { getString(R.string.generic_server) },
                ),
            )
            .putExtra(DicodeVpnService.EXTRA_BYPASS_DOMAINS, settings.bypassDomains)
            // Per-app VPN and VPN sharing controls.
            .putExtra(DicodeVpnService.EXTRA_PER_APP_MODE, settings.perAppVpnMode)
            .putStringArrayListExtra(
                DicodeVpnService.EXTRA_PER_APP_PACKAGES,
                ArrayList(settings.perAppVpnPackages),
            )
            .putExtra(DicodeVpnService.EXTRA_VPN_SHARING_USB, settings.vpnSharingUsb)
            .putExtra(DicodeVpnService.EXTRA_VPN_SHARING_HOTSPOT, settings.vpnSharingHotspot)
        runCatching { ContextCompat.startForegroundService(applicationContext, intent) }
            .onFailure { error ->
                AppLog.e("Main", "VPN foreground service start failed", error)
                VpnStateStore.state.value = VpnState(
                    status = VpnStatus.ERROR,
                    serverId = server.id,
                    serverName = server.name,
                    message = getString(R.string.connection_failed_retry),
                )
            }
    }

    private fun showVpnPermissionError() {
        clearAutomaticQueue()
        MaterialAlertDialogBuilder(this)
            .setTitle(R.string.vpn_permission_failed_title)
            .setMessage(R.string.vpn_permission_failed_message)
            .setPositiveButton(android.R.string.ok, null)
            .show()
    }

    override fun disconnect() {
        AppLog.i("Main", "Disconnect requested")
        pendingScannerStart = false
        scannerLaunchScheduled = false
        clearAutomaticQueue()
        runCatching {
            startService(
                Intent(applicationContext, DicodeVpnService::class.java)
                    .setAction(DicodeVpnService.ACTION_STOP)
            )
        }.onFailure { error ->
            AppLog.e("Main", "VPN stop request failed", error)
            VpnStateStore.state.value = VpnState()
        }
    }


    fun openHomePage() {
        showPage(R.id.nav_servers)
    }


    companion object {
        private const val KEY_CURRENT_PAGE = "current_page"
        private const val KEY_PENDING_SCANNER = "pending_scanner_start"
        private const val AUTO_RETRY_LIMIT = 8
        private const val AUTO_RETRY_DELAY_MS = 450L
    }
}

interface ConnectionHost {
    fun connect(server: ServerRecord? = null)
    fun disconnect()
    fun requestScannerLaunch()
}
