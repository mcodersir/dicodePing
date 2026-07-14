package ir.dicode.ping

import android.content.Context
import android.content.Intent
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
import ir.dicode.ping.util.LocaleHelper
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

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
            view.updatePadding(
                left = bars.left,
                top = bars.top,
                right = bars.right,
                bottom = bars.bottom,
            )
            insets
        }

        val repo = AppRepository.get(applicationContext)
        lifecycleScope.launch {
            repo.progress.collectLatest(::renderProgress)
        }
        lifecycleScope.launch {
            val startedAt = System.currentTimeMillis()
            withTimeoutOrNull(45_000) { repo.initialize() }
            val elapsed = System.currentTimeMillis() - startedAt
            if (elapsed < 650) delay(650 - elapsed)
            val changed = withTimeoutOrNull(5_000) { repo.subscriptionUpdates() }.orEmpty()
            if (changed.isEmpty() || isFinishing) {
                openMain()
            } else {
                val names = changed.take(3).joinToString("، ") { it.name }
                MaterialAlertDialogBuilder(this@SplashActivity)
                    .setTitle(R.string.subscription_update_title)
                    .setMessage(getString(R.string.subscription_update_message, names))
                    .setNegativeButton(R.string.update_later) { _, _ -> openMain() }
                    .setPositiveButton(R.string.update_now) { _, _ ->
                        repo.refreshAll()
                        openMain()
                    }
                    .setCancelable(false)
                    .show()
            }
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
            "ping" -> getString(R.string.splash_testing_servers)
            "geo" -> getString(R.string.splash_locating_servers)
            else -> getString(R.string.splash_preparing)
        }
        binding.progress.isIndeterminate = state.total <= 0
        if (state.total > 0) binding.progress.setProgressCompat(state.percent, true)
    }

    private fun openMain() {
        if (routed || isFinishing) return
        routed = true
        val options = ActivityOptionsCompat.makeCustomAnimation(
            this,
            android.R.anim.fade_in,
            android.R.anim.fade_out,
        )
        startActivity(Intent(this, MainActivity::class.java), options.toBundle())
        finish()
    }
}
