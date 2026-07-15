package ir.dicode.ping.ui

import android.content.res.ColorStateList
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.core.content.ContextCompat
import androidx.core.widget.doAfterTextChanged
import androidx.fragment.app.Fragment
import androidx.fragment.app.activityViewModels
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import androidx.recyclerview.widget.LinearLayoutManager
import com.google.android.material.chip.Chip
import com.google.android.material.snackbar.Snackbar
import ir.dicode.ping.ConnectionHost
import ir.dicode.ping.R
import ir.dicode.ping.databinding.FragmentServersBinding
import ir.dicode.ping.vpn.VpnStateStore
import ir.dicode.ping.vpn.VpnStatus
import ir.dicode.ping.data.ServerPolicy
import kotlinx.coroutines.launch

class ServersFragment : Fragment() {
    private var _binding: FragmentServersBinding? = null
    private val binding get() = _binding!!
    private val vm: MainViewModel by activityViewModels()

    private var sourceId = "all"
    private var query = ""
    private lateinit var adapter: ServerAdapter

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?,
    ): View = FragmentServersBinding.inflate(inflater, container, false).also { _binding = it }.root

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        adapter = ServerAdapter(
            selected = { vm.repo.selectedServerId.value },
            onSelect = { vm.repo.selectServer(it.id, userInitiated = true) },
            onConnect = { (activity as? ConnectionHost)?.connect(it) },
            onFavorite = { vm.repo.setFavorite(it.id) },
            interactionLocked = {
                VpnStateStore.state.value.status == VpnStatus.CONNECTED ||
                    VpnStateStore.state.value.status == VpnStatus.CONNECTING
            },
            onLocked = {
                Snackbar.make(binding.root, R.string.server_change_locked, Snackbar.LENGTH_SHORT).show()
            },
            onRestricted = {
                Snackbar.make(binding.root, R.string.restricted_server_message, Snackbar.LENGTH_SHORT).show()
            },
        )
        binding.serverList.apply {
            layoutManager = LinearLayoutManager(requireContext())
            adapter = this@ServersFragment.adapter
            itemAnimator = null
            setHasFixedSize(false)
            setItemViewCacheSize(8)
        }

        binding.searchInput.editText?.doAfterTextChanged {
            query = it?.toString().orEmpty()
            render()
        }
        binding.refresh.setOnClickListener { vm.repo.refreshAll() }
        binding.pingAll.setOnClickListener { vm.repo.pingAll() }
        binding.connectSelected.setOnClickListener {
            (activity as? ConnectionHost)?.connect(vm.repo.selectedServer())
        }

        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                launch {
                    vm.repo.sources.collect {
                        buildChips()
                        render()
                    }
                }
                launch { vm.repo.servers.collect { render() } }
                launch { vm.repo.selectedServerId.collect { render() } }
                launch {
                    VpnStateStore.state.collect { state ->
                        adapter.notifyItemRangeChanged(0, adapter.itemCount)
                        val locked = state.status == VpnStatus.CONNECTED || state.status == VpnStatus.CONNECTING
                        binding.connectSelected.isEnabled = canConnectSelected(locked)
                    }
                }
                launch {
                    vm.repo.progress.collect { progress ->
                        binding.progress.visibility = if (progress.active) View.VISIBLE else View.GONE
                        binding.progress.progress = progress.percent
                        binding.progressStage.visibility = if (progress.active) View.VISIBLE else View.GONE
                        binding.progressStage.text = when (progress.stage) {
                            "download" -> getString(R.string.stage_downloading, progress.done, progress.total)
                            "geo" -> getString(R.string.stage_location, progress.done, progress.total)
                            "ping" -> getString(R.string.stage_ping, progress.done, progress.total)
                            else -> progress.message
                        }
                        // Keep populated rows visible during location/ping stages so results
                        // animate in-place. Skeletons are only useful before first download.
                        val showSkeleton = progress.active && progress.stage == "download" &&
                            vm.repo.servers.value.isEmpty()
                        binding.skeleton.visibility = if (showSkeleton) View.VISIBLE else View.GONE
                        binding.serverList.visibility = if (showSkeleton) View.INVISIBLE else View.VISIBLE
                        binding.refresh.isEnabled = !progress.active
                        binding.pingAll.isEnabled = !progress.active
                        val locked = VpnStateStore.state.value.status == VpnStatus.CONNECTED ||
                            VpnStateStore.state.value.status == VpnStatus.CONNECTING
                        binding.connectSelected.isEnabled = canConnectSelected(locked)
                        binding.refresh.alpha = if (progress.active) 0.6f else 1f
                        binding.pingAll.alpha = if (progress.active) 0.6f else 1f
                    }
                }
            }
        }
    }

    private fun buildChips() {
        binding.sourceChips.removeAllViews()
        binding.sourceChips.addView(createChip(getString(R.string.all_servers), "all"))
        vm.repo.sources.value.forEach { source ->
            binding.sourceChips.addView(createChip(source.name, source.id))
        }
    }

    private fun createChip(label: String, id: String): Chip = Chip(requireContext()).apply {
        text = label
        isCheckable = true
        isChecked = sourceId == id
        isCheckedIconVisible = false
        chipMinHeight = dp(34).toFloat()
        shapeAppearanceModel = shapeAppearanceModel.toBuilder()
            .setAllCornerSizes(dp(12).toFloat())
            .build()
        chipStrokeWidth = dp(1).toFloat()
        chipStrokeColor = ColorStateList.valueOf(
            ContextCompat.getColor(requireContext(), R.color.outline_soft),
        )
        chipBackgroundColor = ContextCompat.getColorStateList(requireContext(), R.color.chip_background)
        setTextColor(ContextCompat.getColorStateList(requireContext(), R.color.chip_text))
        textSize = 11f
        setOnClickListener {
            sourceId = id
            render()
        }
    }

    private fun render() {
        val normalizedQuery = query.trim()
        val rows = vm.repo.servers.value.filter { server ->
            (sourceId == "all" || server.sourceId == sourceId) &&
                (normalizedQuery.isBlank() || listOf(
                    server.name,
                    server.host,
                    server.country,
                    server.region,
                    server.city,
                    server.isp,
                ).any { it.contains(normalizedQuery, ignoreCase = true) })
        }
        adapter.submitList(rows)
        binding.serverCount.text = getString(R.string.server_results_count, rows.size)
        val locked = VpnStateStore.state.value.status == VpnStatus.CONNECTED ||
            VpnStateStore.state.value.status == VpnStatus.CONNECTING
        binding.connectSelected.isEnabled = canConnectSelected(locked)
        binding.empty.visibility = if (rows.isEmpty() && !vm.repo.progress.value.active) {
            View.VISIBLE
        } else {
            View.GONE
        }
    }

    private fun dp(value: Int): Int =
        (value * resources.displayMetrics.density).toInt().coerceAtLeast(1)

    private fun canConnectSelected(locked: Boolean): Boolean {
        val selected = vm.repo.selectedServer()
        return !locked && !vm.repo.progress.value.active && selected != null && !ServerPolicy.isRestricted(selected)
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
