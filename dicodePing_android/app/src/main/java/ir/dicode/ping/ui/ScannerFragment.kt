package ir.dicode.ping.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.fragment.app.Fragment
import androidx.fragment.app.activityViewModels
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.google.android.material.snackbar.Snackbar
import ir.dicode.ping.R
import ir.dicode.ping.data.SourceDefinition
import ir.dicode.ping.databinding.FragmentScannerBinding
import ir.dicode.ping.net.TelegramChannelCrawler
import ir.dicode.ping.net.VolumeDetector
import ir.dicode.ping.net.SubscriptionClient
import ir.dicode.ping.util.RuntimeTuning
import ir.dicode.ping.vpn.VpnStateStore
import ir.dicode.ping.vpn.VpnStatus
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull

/**
 * One-click scanner fragment (Android mirror of the desktop scanner page).
 *
 * v1.6.0-rc.2 changes:
 *  - The "Quick scan" button now crawls Telegram channels (via the
 *    program's own running VPN) instead of re-fetching the default
 *    subscription.
 *  - The "Fetch volumes" button now issues real HEAD requests to every
 *    enabled subscription URL and parses the ``Subscription-Userinfo``
 *    header for the actual remaining quota — not just the remark.
 *  - The UI is more minimal: one big primary button, an optional name
 *    field, a single status line, a slim progress bar, and a copy-all
 *    button.  No settings exposed.
 */
class ScannerFragment : Fragment() {
    private var _binding: FragmentScannerBinding? = null
    private val binding get() = _binding!!
    private val vm: MainViewModel by activityViewModels()

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?,
    ): View = FragmentScannerBinding.inflate(inflater, container, false).also { _binding = it }.root

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        // --- Quick scan -------------------------------------------------
        binding.scannerRunButton.setOnClickListener {
            val customName = binding.scannerNameEdit.text?.toString().orEmpty().trim()
            startScan(customName)
        }

        // --- Fetch volumes ---------------------------------------------
        binding.volumeFetchButton.setOnClickListener {
            startVolumeFetch()
        }

        // --- Copy all servers ------------------------------------------
        binding.copyAllButton.setOnClickListener {
            val servers = vm.repo.servers.value
            if (servers.isEmpty()) {
                Snackbar.make(binding.root, R.string.scanner_empty_history, Snackbar.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            val payload = servers.joinToString("\n") { it.raw }
            val clipboard = requireContext().getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            clipboard.setPrimaryClip(ClipData.newPlainText("dicodePing", payload))
            Snackbar.make(binding.root, R.string.scanner_copy_done, Snackbar.LENGTH_SHORT).show()
        }

        // --- Observe repository progress + servers --------------------
        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                launch {
                    vm.repo.progress.collect { progress ->
                        val active = progress.active
                        binding.scannerProgressBar.visibility = if (active) View.VISIBLE else View.GONE
                        binding.scannerStageLabel.visibility = if (active) View.VISIBLE else View.GONE
                        if (active) {
                            binding.scannerProgressBar.progress = progress.percent
                            binding.scannerStageLabel.text = when (progress.stage) {
                                "download" -> getString(R.string.stage_downloading, progress.done, progress.total)
                                "geo" -> getString(R.string.stage_location, progress.done, progress.total)
                                "ping" -> getString(R.string.stage_ping, progress.done, progress.total)
                                else -> progress.message
                            }
                        }
                        binding.scannerRunButton.isEnabled = !active
                    }
                }
                launch {
                    vm.repo.servers.collect { servers ->
                        if (servers.isEmpty()) {
                            binding.scannerHistoryEmpty.visibility = View.VISIBLE
                            binding.scannerHistoryContent.visibility = View.GONE
                        } else {
                            binding.scannerHistoryEmpty.visibility = View.GONE
                            binding.scannerHistoryContent.visibility = View.VISIBLE
                            binding.scannerHistoryContent.text = resources.getQuantityString(
                                R.plurals.scanner_servers_count,
                                servers.size,
                                servers.size,
                            )
                        }
                    }
                }
            }
        }
    }

    /**
     * Kick off the Telegram-channel scan in the background.
     *
     * The crawler runs through the program's own VPN, so the user must
     * be connected (or at least have the default subscription loaded)
     * before this will produce results.
     */
    private fun startScan(customName: String) {
        binding.scannerRunButton.isEnabled = false
        binding.scannerRunButton.text = getString(R.string.scanner_running)
        binding.scannerProgressBar.visibility = View.VISIBLE
        binding.scannerProgressBar.isIndeterminate = true
        binding.scannerStageLabel.visibility = View.VISIBLE
        binding.scannerStageLabel.text = getString(R.string.scanner_crawl)
        binding.scannerResultLabel.text = ""

        viewLifecycleOwner.lifecycleScope.launch {
            val connectionHost = activity as? ConnectionHost
            val result = runCatching {
                if (VpnStateStore.state.value.status != VpnStatus.CONNECTED) {
                    binding.scannerStageLabel.text = getString(R.string.connecting)
                    connectionHost?.connect(null)
                    val state = withTimeoutOrNull(30_000) {
                        VpnStateStore.state.first {
                            it.status == VpnStatus.CONNECTED || it.status == VpnStatus.ERROR
                        }
                    }
                    check(state?.status == VpnStatus.CONNECTED) {
                        state?.message ?: getString(R.string.connection_failed_retry)
                    }
                }

                binding.scannerStageLabel.text = getString(R.string.scanner_crawl)
                val channels = loadChannelsFromAssets()
                val tuning = RuntimeTuning.detect(requireContext())
                val configs = withContext(Dispatchers.IO) {
                    TelegramChannelCrawler.crawl(channels, tuning.crawlWorkers) { done, total, _ ->
                        viewLifecycleOwner.lifecycleScope.launch {
                            if (total > 0 && _binding != null) {
                                binding.scannerProgressBar.isIndeterminate = false
                                binding.scannerProgressBar.progress = (done * 45 / total)
                            }
                        }
                    }
                }
                check(configs.isNotEmpty()) { getString(R.string.scanner_no_result) }

                binding.scannerStageLabel.text = getString(R.string.stage_ping, 0, configs.size)
                connectionHost?.disconnect()
                withTimeoutOrNull(8_000) {
                    VpnStateStore.state.first { it.status == VpnStatus.DISCONNECTED }
                }

                val imported = vm.repo.importScannerConfigs(configs)
                check(imported.isNotEmpty()) { getString(R.string.scanner_no_result) }
                Triple(configs.size, imported.size, imported.count { it.healthy })
            }

            binding.scannerProgressBar.isIndeterminate = false
            binding.scannerProgressBar.progress = if (result.isSuccess) 100 else 0
            binding.scannerRunButton.isEnabled = true
            binding.scannerRunButton.text = getString(R.string.scanner_run)
            binding.scannerStageLabel.text = getString(R.string.scanner_done)

            val summary = result.getOrNull()
            if (summary == null) {
                binding.scannerResultLabel.text = result.exceptionOrNull()?.message
                    ?: getString(R.string.scanner_no_result)
                return@launch
            }
            val message = getString(R.string.scanner_result, summary.first, summary.second, summary.third)
            binding.scannerResultLabel.text = message
            Snackbar.make(binding.root, message, Snackbar.LENGTH_LONG).show()
            vm.repo.bestServer()?.let { connectionHost?.connect(it) }
        }
    }

    private fun loadChannelsFromAssets(): List<String> {
        val out = mutableListOf<String>()
        try {
            val text = requireContext().assets.open("channels.txt").bufferedReader().readText()
            for (raw in text.split("\n")) {
                val line = raw.trim()
                if (line.isBlank() || line.startsWith("#")) continue
                out.add(line.removePrefix("t.me/").removePrefix("https://t.me/").trim('/'))
            }
        } catch (_: Exception) {
            // Fall back to an empty list; the scanner will surface a
            // friendly error to the user.
        }
        return out
    }

    /**
     * Refresh real volume info for every saved server in one shot.
     *
     * Issues HEAD requests in parallel for every enabled subscription
     * URL, reads the ``Subscription-Userinfo`` header, and reports the
     * remaining quota to the user via the result label.
     */
    private fun startVolumeFetch() {
        val servers = vm.repo.servers.value
        if (servers.isEmpty()) {
            Snackbar.make(binding.root, R.string.scanner_empty_history, Snackbar.LENGTH_SHORT).show()
            return
        }
        binding.volumeFetchButton.isEnabled = false
        binding.volumeFetchButton.text = getString(R.string.volume_fetching)

        viewLifecycleOwner.lifecycleScope.launch {
            val sources = vm.repo.sources.value
            val sourceUrls: Map<String, String> = sources.associate { it.id to it.url }.filterValues { it.isNotBlank() }
            val client = SubscriptionClient()

            // Fetch HEAD for each unique source URL in parallel.
            val quotas = withContext(Dispatchers.IO) {
                val uniqueUrls = sourceUrls.values.toSet()
                uniqueUrls.mapNotNull { url ->
                    runCatching {
                        val header = client.fetchUserinfoHeader(url)
                        url to (VolumeDetector.parseUserinfo(header) ?: return@runCatching null)
                    }.getOrNull()
                }.toMap()
            }

            // Count servers with real quota data.
            val withQuota = servers.count { server ->
                val url = sourceUrls[server.sourceId] ?: return@count false
                quotas[url] != null
            }
            val withRemark = servers.count { VolumeDetector.detectFromServer(it).isVolume }

            binding.volumeFetchButton.isEnabled = true
            binding.volumeFetchButton.text = getString(R.string.volume_fetch)
            val msg = getString(R.string.volume_summary, withQuota + withRemark, servers.size)
            binding.scannerResultLabel.text = msg
            Snackbar.make(binding.root, msg, Snackbar.LENGTH_LONG).show()
        }
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
