package ir.dicode.ping.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.app.Activity
import android.net.VpnService
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import androidx.fragment.app.activityViewModels
import androidx.activity.result.contract.ActivityResultContracts
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.google.android.material.snackbar.Snackbar
import ir.dicode.ping.R
import ir.dicode.ping.databinding.FragmentScannerBinding
import ir.dicode.ping.scanner.ScannerCoordinator
import ir.dicode.ping.scanner.ScannerService
import kotlinx.coroutines.launch

/**
 * Renderer/controller for the application-owned ScannerCoordinator.
 * No scan job is owned by this Fragment, so navigation, rotation and theme
 * recreation cannot cancel the active session.
 */
class ScannerFragment : Fragment() {
    // Pipeline ownership moved to ScannerCoordinator:
    // importScannerConfigs(configs, customName)
    private var _binding: FragmentScannerBinding? = null
    private val binding get() = _binding!!
    private val vm: MainViewModel by activityViewModels()
    private var scannerStartPending = false
    private val vpnPermission = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val shouldStart = scannerStartPending
        scannerStartPending = false
        val activeBinding = _binding
        activeBinding?.scannerRunButton?.isEnabled = true
        if (!shouldStart || !isAdded) return@registerForActivityResult
        if (result.resultCode == Activity.RESULT_OK && VpnService.prepare(requireContext()) == null) {
            startScannerService()
        } else {
            activeBinding?.root?.let { root ->
                Snackbar.make(root, R.string.vpn_permission_failed_message, Snackbar.LENGTH_LONG).show()
            }
        }
    }

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?,
    ): View = FragmentScannerBinding.inflate(inflater, container, false).also { _binding = it }.root

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        val coordinator = ScannerCoordinator.get(requireContext())
        binding.scannerRunButton.setOnClickListener {
            if (coordinator.state.value.running) {
                requireContext().startService(
                    Intent(requireContext(), ScannerService::class.java).setAction(ScannerService.ACTION_STOP)
                )
            } else {
                beginScannerWithVpnPermission()
            }
        }
        binding.copyAllButton.setOnClickListener {
            val servers = vm.repo.servers.value.filter { it.sourceId == "scanner-sub" && it.healthy }
            if (servers.isEmpty()) {
                Snackbar.make(binding.root, R.string.scanner_empty_history, Snackbar.LENGTH_SHORT).show()
            } else {
                val clipboard = requireContext().getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                clipboard.setPrimaryClip(ClipData.newPlainText("dicodePing", servers.joinToString("\n") { it.raw }))
                Snackbar.make(binding.root, R.string.scanner_copy_done, Snackbar.LENGTH_SHORT).show()
            }
        }

        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                launch {
                    coordinator.state.collect { state ->
                        binding.scannerProgressBar.visibility = if (state.running || state.progress > 0) View.VISIBLE else View.GONE
                        binding.scannerProgressBar.isIndeterminate = state.total == 0 && state.running
                        binding.scannerProgressBar.progress = state.progress
                        binding.scannerStageLabel.visibility = View.VISIBLE
                        binding.scannerStageLabel.text = buildString {
                            append(state.stage.name.lowercase())
                            if (state.total > 0) append(" • ${state.done}/${state.total}")
                            append(" • ${state.alive} healthy")
                        }
                        binding.scannerResultLabel.text = state.result
                        binding.scannerRunButton.text = getString(
                            if (state.running) R.string.scanner_stop_save else R.string.scanner_run
                        )
                    }
                }
                launch {
                    vm.repo.servers.collect { servers ->
                        val count = servers.count { it.sourceId == "scanner-sub" && it.healthy }
                        binding.scannerHistoryEmpty.visibility = if (count == 0) View.VISIBLE else View.GONE
                        binding.scannerHistoryContent.visibility = if (count == 0) View.GONE else View.VISIBLE
                        if (count > 0) {
                            binding.scannerHistoryContent.text = resources.getQuantityString(
                                R.plurals.scanner_servers_count,
                                count,
                                count,
                            )
                        }
                    }
                }
            }
        }
    }

    private fun beginScannerWithVpnPermission() {
        val permissionIntent = runCatching { VpnService.prepare(requireContext()) }.getOrNull()
        if (permissionIntent == null) {
            startScannerService()
        } else {
            scannerStartPending = true
            binding.scannerRunButton.isEnabled = false
            binding.scannerRunButton.text = getString(R.string.preparing_vpn)
            vpnPermission.launch(permissionIntent)
        }
    }

    private fun startScannerService() {
        if (!isAdded) return
        _binding?.scannerRunButton?.apply {
            isEnabled = true
            text = getString(R.string.preparing_vpn)
        }
        runCatching {
            ContextCompat.startForegroundService(
                requireContext(),
                Intent(requireContext(), ScannerService::class.java)
                    .putExtra(ScannerService.EXTRA_NAME, "SUB"),
            )
        }.onFailure { error ->
            _binding?.scannerRunButton?.text = getString(R.string.scanner_run)
            _binding?.root?.let { root ->
                Snackbar.make(root, error.message ?: getString(R.string.connection_failed_retry), Snackbar.LENGTH_LONG).show()
            }
        }
    }

    override fun onDestroyView() {
        _binding = null
        super.onDestroyView()
    }
}
