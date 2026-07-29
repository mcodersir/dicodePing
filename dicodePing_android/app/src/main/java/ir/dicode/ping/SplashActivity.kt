package ir.dicode.ping

import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.enableEdgeToEdge
import androidx.core.app.ActivityOptionsCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.updatePadding
import androidx.lifecycle.lifecycleScope
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import ir.dicode.ping.data.AppRepository
import ir.dicode.ping.data.ProgressState
import ir.dicode.ping.data.SettingsStore
import ir.dicode.ping.databinding.ActivitySplashBinding
import ir.dicode.ping.net.AppRelease
import ir.dicode.ping.net.ReleaseUpdateChecker
import ir.dicode.ping.util.AppLog
import ir.dicode.ping.util.LocaleHelper
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

// Legacy full-refresh hook retained as background-only policy: repo.refreshAllAndWait()
@SuppressLint("CustomSplashScreen")
class SplashActivity : ComponentActivity() {
    private lateinit var binding: ActivitySplashBinding
    private var routed = false

    override fun attachBaseContext(newBase: Context) {
        super.attachBaseContext(LocaleHelper.wrap(newBase, SettingsStore(newBase).language))
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        binding = ActivitySplashBinding.inflate(layoutInflater)
        setContentView(binding.root)

        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { view, insets ->
            val bars = insets.getInsets(
                WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout(),
            )
            view.updatePadding(left = bars.left, top = bars.top, right = bars.right, bottom = bars.bottom)
            insets
        }

        val repo = AppRepository.get(applicationContext)
        lifecycleScope.launch { repo.progress.collectLatest(::renderProgress) }
        lifecycleScope.launch {
            val startedAt = System.currentTimeMillis()
            val startupCompleted = withTimeoutOrNull(STARTUP_PIPELINE_TIMEOUT_MS) {
                repo.initialize()
                true
            } == true
            if (!startupCompleted) {
                AppLog.w("Splash", "Startup preparation reached its time budget; opening with cached data")
                repo.cancelStartupProgress()
            }

            // A short revision check keeps the historical update contract without
            // allowing a slow source to hold the splash indefinitely.
            withTimeoutOrNull(SOURCE_REVISION_TIMEOUT_MS) { repo.subscriptionUpdates() }
            repo.showUpdateProgress()
            val release = withTimeoutOrNull(UPDATE_CHECK_TIMEOUT_MS) {
                ReleaseUpdateChecker.newerThan(BuildConfig.RELEASE_VERSION)
            }
            repo.cancelStartupProgress()

            val elapsed = System.currentTimeMillis() - startedAt
            if (elapsed < MIN_SPLASH_MS) delay(MIN_SPLASH_MS - elapsed)
            showStartupPrompts(release)
        }
    }

    private fun showStartupPrompts(release: AppRelease?) {
        if (isFinishing) return
        if (release != null) {
            MaterialAlertDialogBuilder(this)
                .setTitle(getString(R.string.app_update_title, release.tag))
                .setMessage(R.string.app_update_message)
                .setNegativeButton(R.string.update_later) { _, _ -> openMain() }
                .setPositiveButton(R.string.update_now) { _, _ ->
                    startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(release.assetUrl)))
                    openMain()
                }
                .setCancelable(false)
                .show()
        } else {
            openMain()
        }
    }

    private fun renderProgress(state: ProgressState) {
        if (!state.active) {
            binding.progress.isIndeterminate = true
            binding.status.setText(R.string.splash_preparing)
            return
        }
        binding.status.text = when (state.stage) {
            "download" -> getString(R.string.splash_updating_servers)
            "startup_ping", "ping" -> getString(R.string.splash_testing_sample)
            "update" -> getString(R.string.splash_checking_updates)
            "cores" -> getString(R.string.splash_checking_cores)
            else -> getString(R.string.splash_preparing)
        }
        binding.progress.isIndeterminate = state.total <= 0
        if (state.total > 0) binding.progress.setProgressCompat(state.percent, true)
    }

    private fun openMain() {
        if (routed || isFinishing) return
        routed = true
        AppRepository.get(applicationContext).finishStartupInBackground()
        val options = ActivityOptionsCompat.makeCustomAnimation(
            this,
            android.R.anim.fade_in,
            android.R.anim.fade_out,
        )
        startActivity(Intent(this, MainActivity::class.java), options.toBundle())
        finish()
    }

    private companion object {
        const val STARTUP_PIPELINE_TIMEOUT_MS = 38_000L
        const val SOURCE_REVISION_TIMEOUT_MS = 1_500L
        const val UPDATE_CHECK_TIMEOUT_MS = 4_000L
        const val MIN_SPLASH_MS = 650L
    }
}
