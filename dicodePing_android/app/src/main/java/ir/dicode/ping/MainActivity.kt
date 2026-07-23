package ir.dicode.ping

import android.Manifest
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.content.res.Configuration
import android.net.VpnService
import android.os.Build
import android.os.Bundle
import android.view.HapticFeedbackConstants
import android.view.View
import android.widget.ImageView
import androidx.activity.SystemBarStyle
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
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
import ir.dicode.ping.ui.HomeFragment
import ir.dicode.ping.ui.MainViewModel
import ir.dicode.ping.ui.ScannerFragment
import ir.dicode.ping.ui.ServersFragment
import ir.dicode.ping.ui.SettingsFragment
import ir.dicode.ping.util.AppLog
import ir.dicode.ping.util.LocaleHelper
import ir.dicode.ping.util.PublicServerLabel
import ir.dicode.ping.vpn.DicodeVpnService
import ir.dicode.ping.vpn.VpnStateStore
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

    private val vpnPermission = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { _ ->
        val server = pendingServer ?: return@registerForActivityResult
        pendingServer = null

        lifecycleScope.launch {
            var granted = false
            for (attempt in 0 until 4) {
                delay(300)
                granted = runCatching { VpnService.prepare(this@MainActivity) == null }.getOrDefault(false)
                if (granted) break
            }
            if (granted) startVpn(server) else showVpnPermissionError()
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

        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED
        ) {
            notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }

        bindNavigationItem(binding.navHome, binding.navHomeIcon, R.id.nav_home)
        bindNavigationItem(binding.navServers, binding.navServersIcon, R.id.nav_servers)
        bindNavigationItem(binding.navScanner, binding.navScannerIcon, R.id.nav_scanner)
        bindNavigationItem(binding.navSettings, binding.navSettingsIcon, R.id.nav_settings)
        bindNavigationItem(binding.navAbout, binding.navAboutIcon, R.id.nav_about)

        val restoredPage = savedInstanceState?.getInt(KEY_CURRENT_PAGE, R.id.nav_home) ?: R.id.nav_home
        currentPageId = 0
        showPage(restoredPage, animate = false)

        lifecycleScope.launch {
            VpnStateStore.state.collect { state ->
                when {
                    state.status == ir.dicode.ping.vpn.VpnStatus.CONNECTED &&
                        state.serverId == automaticAttemptId -> clearAutomaticQueue()
                    state.status == ir.dicode.ping.vpn.VpnStatus.ERROR &&
                        state.serverId == automaticAttemptId &&
                        automaticAttemptId.isNotBlank() &&
                        !automaticRetryScheduled -> retryAutomaticConnection()
                }
            }
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        outState.putInt(KEY_CURRENT_PAGE, currentPageId.takeIf { it != 0 } ?: R.id.nav_home)
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

            binding.fragmentHost.updatePadding(
                left = statusAndCutout.left,
                top = statusAndCutout.top,
                right = statusAndCutout.right,
            )
            binding.navContainer.updatePadding(
                left = navigation.left,
                right = navigation.right,
                bottom = navigation.bottom,
            )
            windowInsets
        }
        ViewCompat.requestApplyInsets(binding.root)
    }

    private fun bindNavigationItem(container: View, icon: ImageView, destination: Int) {
        container.setOnClickListener {
            container.performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP)
            showPage(destination)
            icon.animate().cancel()
            icon.scaleX = 0.92f
            icon.scaleY = 0.92f
            icon.animate()
                .scaleX(1f)
                .scaleY(1f)
                .setDuration(100L)
                .start()
        }
    }

    private fun showPage(id: Int, animate: Boolean = true) {
        val tag = pageTag(id)
        val existing = supportFragmentManager.findFragmentByTag(tag)
        if (id == currentPageId && existing?.isVisible == true) return

        AppLog.i("Navigation", "Open destination=$id")
        currentPageId = id
        val target = existing ?: createPage(id)
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
        updateNavigationSelection(id)
    }

    private fun createPage(id: Int): Fragment = when (id) {
        R.id.nav_servers -> ServersFragment()
        R.id.nav_scanner -> ScannerFragment()
        R.id.nav_settings -> SettingsFragment()
        R.id.nav_about -> AboutFragment()
        else -> HomeFragment()
    }

    private fun pageTag(id: Int): String = "main_page_$id"

    private fun updateNavigationSelection(selectedId: Int) {
        binding.navHome.isSelected = selectedId == R.id.nav_home
        binding.navServers.isSelected = selectedId == R.id.nav_servers
        binding.navScanner.isSelected = selectedId == R.id.nav_scanner
        binding.navSettings.isSelected = selectedId == R.id.nav_settings
        binding.navAbout.isSelected = selectedId == R.id.nav_about
        binding.navHomeIcon.isSelected = binding.navHome.isSelected
        binding.navServersIcon.isSelected = binding.navServers.isSelected
        binding.navScannerIcon.isSelected = binding.navScanner.isSelected
        binding.navSettingsIcon.isSelected = binding.navSettings.isSelected
        binding.navAboutIcon.isSelected = binding.navAbout.isSelected
    }

    override fun connect(server: ServerRecord?) {
        if (vm.repo.progress.value.active) {
            MaterialAlertDialogBuilder(this)
                .setTitle(R.string.preparing_servers)
                .setMessage(R.string.servers_still_preparing)
                .setPositiveButton(android.R.string.ok, null)
                .show()
            return
        }
        if (server == null && vm.repo.connectionMode.value == "auto") {
            val candidates = vm.repo.automaticCandidates(AUTO_RETRY_LIMIT)
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
            MaterialAlertDialogBuilder(this)
                .setTitle(R.string.no_server_title)
                .setMessage(R.string.no_server_message)
                .setPositiveButton(android.R.string.ok, null)
                .show()
            return
        }
        if (ServerPolicy.isRestricted(candidate)) {
            MaterialAlertDialogBuilder(this)
                .setTitle(R.string.server_disabled)
                .setMessage(R.string.restricted_server_message)
                .setPositiveButton(android.R.string.ok, null)
                .show()
            return
        }

        clearAutomaticQueue()
        prepareAndStart(candidate)
    }

    private fun prepareAndStart(candidate: ServerRecord) {
        vm.repo.selectServer(candidate.id, userInitiated = false)
        val prepareIntent = runCatching { VpnService.prepare(this) }.getOrNull()
        if (prepareIntent != null) {
            pendingServer = candidate
            vpnPermission.launch(prepareIntent)
        } else {
            startVpn(candidate)
        }
    }

    private suspend fun retryAutomaticConnection() {
        automaticRetryScheduled = true
        delay(AUTO_RETRY_DELAY_MS)
        val next = automaticQueue.removeFirstOrNull()
        if (next == null) {
            clearAutomaticQueue()
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
            .putExtra(DicodeVpnService.EXTRA_BYPASS_DOMAINS, vm.repo.settings.bypassDomains)
            .putStringArrayListExtra(
                DicodeVpnService.EXTRA_BYPASS_APPS,
                ArrayList(vm.repo.settings.bypassApps),
            )
        ContextCompat.startForegroundService(applicationContext, intent)
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
        clearAutomaticQueue()
        startService(
            Intent(applicationContext, DicodeVpnService::class.java)
                .setAction(DicodeVpnService.ACTION_STOP)
        )
    }

    companion object {
        private const val KEY_CURRENT_PAGE = "current_page"
        private const val AUTO_RETRY_LIMIT = 5
        private const val AUTO_RETRY_DELAY_MS = 450L
    }
}

interface ConnectionHost {
    fun connect(server: ServerRecord? = null)
    fun disconnect()
}
