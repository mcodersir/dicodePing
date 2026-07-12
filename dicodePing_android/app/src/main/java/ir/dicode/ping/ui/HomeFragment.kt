package ir.dicode.ping.ui

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import androidx.fragment.app.activityViewModels
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import ir.dicode.ping.ConnectionHost
import ir.dicode.ping.R
import ir.dicode.ping.data.ServerRecord
import ir.dicode.ping.databinding.FragmentHomeBinding
import ir.dicode.ping.util.PublicServerLabel
import ir.dicode.ping.vpn.VpnState
import ir.dicode.ping.vpn.VpnStateStore
import ir.dicode.ping.vpn.VpnStatus
import kotlinx.coroutines.launch
import java.util.Locale

class HomeFragment : Fragment() {
    private var _binding: FragmentHomeBinding? = null
    private val binding get() = _binding!!
    private val vm: MainViewModel by activityViewModels()

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?,
    ): View = FragmentHomeBinding.inflate(inflater, container, false).also { _binding = it }.root

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        binding.connectButton.setOnClickListener {
            when (VpnStateStore.state.value.status) {
                VpnStatus.CONNECTED -> (activity as? ConnectionHost)?.disconnect()
                VpnStatus.CONNECTING -> Unit
                else -> (activity as? ConnectionHost)?.connect()
            }
        }
        binding.refreshButton.setOnClickListener { vm.repo.refreshAll() }
        binding.pingButton.setOnClickListener { vm.repo.pingAll() }

        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                launch { vm.repo.servers.collect { renderServerSummary() } }
                launch { vm.repo.selectedServerId.collect { renderConnectionTarget() } }
                launch { vm.repo.connectionMode.collect { renderConnectionTarget() } }
                launch {
                    vm.repo.progress.collect { progress ->
                        binding.progressCard.visibility = if (progress.active) View.VISIBLE else View.GONE
                        binding.progressBar.progress = progress.percent.coerceIn(0, 100)
                        binding.progressText.text = progress.message
                        binding.progressPercent.text = getString(
                            R.string.percent_value,
                            progress.percent.coerceIn(0, 100),
                        )
                    }
                }
                launch { VpnStateStore.state.collect(::renderVpnState) }
            }
        }
    }

    private fun renderServerSummary() {
        val rows = vm.repo.servers.value
        val best = vm.repo.bestServer()
        binding.savedValue.text = rows.size.toString()
        binding.healthyValue.text = rows.count { it.healthy }.toString()
        binding.bestValue.text = best?.pingMs?.let { "$it ms" }
            ?: getString(R.string.server_temporarily_unavailable_short)
        renderConnectionTarget()
    }

    private fun renderConnectionTarget() {
        if (_binding == null) return
        val vpnState = VpnStateStore.state.value
        val target = if (vpnState.status in setOf(VpnStatus.CONNECTED, VpnStatus.CONNECTING) && vpnState.serverId.isNotBlank()) {
            vm.repo.serverById(vpnState.serverId) ?: vm.repo.connectionTarget()
        } else {
            vm.repo.connectionTarget()
        }
        binding.recommendedLabel.text = when {
            vpnState.status == VpnStatus.CONNECTED -> getString(R.string.connected_server)
            vpnState.status == VpnStatus.CONNECTING -> getString(R.string.connecting_server)
            vm.repo.connectionMode.value == "manual" -> getString(R.string.selected_connection_server)
            else -> getString(R.string.automatic_connection_server)
        }
        bindTarget(target)
    }

    private fun bindTarget(server: ServerRecord?) {
        binding.bestFlag.text = server?.countryCode?.let(::flag).orEmpty().ifBlank { "🌐" }
        if (server == null) {
            binding.bestServer.text = getString(R.string.no_server)
            binding.bestServerMeta.text = getString(R.string.select_server_for_connection)
            return
        }
        val fallback = server.city.ifBlank {
            server.country.ifBlank { getString(R.string.generic_server) }
        }
        binding.bestServer.text = PublicServerLabel.name(server.name, fallback)
        val location = listOf(server.city, server.region, server.country)
            .filter(String::isNotBlank)
            .distinct()
            .joinToString(" • ")
            .ifBlank { getString(R.string.server_details) }
        val latency = server.pingMs?.let { " • $it ms" }
            ?: " • ${getString(R.string.server_temporarily_unavailable)}"
        binding.bestServerMeta.text = "$location$latency"
    }

    private fun renderVpnState(state: VpnState) {
        val connected = state.status == VpnStatus.CONNECTED
        val connecting = state.status == VpnStatus.CONNECTING
        val color = when (state.status) {
            VpnStatus.CONNECTED -> R.color.success
            VpnStatus.CONNECTING -> R.color.warning
            VpnStatus.ERROR -> R.color.danger
            VpnStatus.DISCONNECTED -> R.color.text_secondary
        }
        val label = when (state.status) {
            VpnStatus.CONNECTED -> getString(R.string.connected)
            VpnStatus.CONNECTING -> getString(R.string.connecting)
            VpnStatus.ERROR -> getString(R.string.connection_error)
            VpnStatus.DISCONNECTED -> getString(R.string.ready_to_connect)
        }

        binding.statusDot.setTextColor(ContextCompat.getColor(requireContext(), color))
        binding.statusBadge.setTextColor(ContextCompat.getColor(requireContext(), color))
        binding.statusBadge.text = label
        binding.statusTitle.text = when (state.status) {
            VpnStatus.CONNECTED -> getString(R.string.home_connected_title)
            VpnStatus.CONNECTING -> getString(R.string.home_connecting_title)
            VpnStatus.ERROR -> getString(R.string.home_error_title)
            VpnStatus.DISCONNECTED -> getString(R.string.home_ready_title)
        }
        binding.statusDetail.text = state.message.ifBlank {
            state.serverName.ifBlank { getString(R.string.connection_status_hint) }
        }
        binding.connectButton.isEnabled = !connecting
        binding.connectButton.alpha = if (connecting) 0.72f else 1f
        binding.connectButton.text = when {
            connected -> getString(R.string.disconnect)
            connecting -> getString(R.string.connecting)
            else -> getString(R.string.connect_target_server)
        }

        binding.liveMetricsGroup.visibility = if (connected) View.VISIBLE else View.GONE
        binding.downloadValue.text = formatBytes(state.downloadBytes)
        binding.uploadValue.text = formatBytes(state.uploadBytes)
        binding.connectedPingValue.text = state.pingMs?.let { "$it ms" }
            ?: getString(R.string.server_temporarily_unavailable_short)
        renderConnectionTarget()
    }

    private fun formatBytes(bytes: Long): String {
        val safe = bytes.coerceAtLeast(0L).toDouble()
        val units = arrayOf("B", "KB", "MB", "GB", "TB")
        var value = safe
        var unit = 0
        while (value >= 1024.0 && unit < units.lastIndex) {
            value /= 1024.0
            unit++
        }
        val pattern = if (unit == 0) "%.0f %s" else "%.1f %s"
        return String.format(Locale.US, pattern, value, units[unit])
    }

    private fun flag(code: String): String {
        if (code.length != 2) return ""
        return code.uppercase(Locale.US).map { character ->
            String(Character.toChars(0x1F1E6 + character.code - 'A'.code))
        }.joinToString("")
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
