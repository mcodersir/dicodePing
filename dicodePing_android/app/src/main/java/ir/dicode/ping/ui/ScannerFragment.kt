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
import ir.dicode.ping.databinding.FragmentScannerBinding
import ir.dicode.ping.net.VolumeDetector
import kotlinx.coroutines.launch

/**
 * One-click scanner fragment (Android mirror of the desktop scanner page).
 *
 * The user explicitly asked for the scanner to be a single button that
 * produces a result.  All tunable settings (concurrency, timeouts, retry
 * budget) live in the repository and are not exposed in the UI.
 *
 * When the user taps "Quick scan" we ask the repository to refresh all
 * sources, drop every server that did not respond, and persist the
 * survivors as an internal scanner sub.  The "Copy all" button copies
 * every server URI to the clipboard so the user can paste it into
 * v2rayNG or any other client.
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
        binding.scannerRunButton.setOnClickListener {
            // The scanner reuses the existing refreshAllAndWait flow.
            // The repository already drops servers that do not respond
            // to the real-tunnel ping, so the result is exactly what the
            // user asked for: a one-click "scan and keep only live".
            vm.repo.refreshAll()
            Snackbar.make(binding.root, R.string.scanner_running, Snackbar.LENGTH_SHORT).show()
        }

        binding.volumeFetchButton.setOnClickListener {
            val servers = vm.repo.servers.value
            if (servers.isEmpty()) {
                Snackbar.make(binding.root, R.string.scanner_empty_history, Snackbar.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            // The volume detection runs synchronously on each row
            // (it only inspects the remark string).  We compute the
            // counts and report them to the user via the result label.
            val withVolume = servers.count { VolumeDetector.detectFromServer(it).isVolume }
            val label = getString(R.string.volume_summary, withVolume, servers.size)
            binding.scannerResultLabel.text = label
            Snackbar.make(binding.root, label, Snackbar.LENGTH_LONG).show()
        }

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

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
