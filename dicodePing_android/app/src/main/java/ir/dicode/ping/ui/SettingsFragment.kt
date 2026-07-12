package ir.dicode.ping.ui

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ArrayAdapter
import androidx.appcompat.app.AppCompatDelegate
import androidx.fragment.app.Fragment
import androidx.fragment.app.activityViewModels
import androidx.core.widget.doAfterTextChanged
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.android.material.snackbar.Snackbar
import com.google.android.material.tabs.TabLayout
import ir.dicode.ping.R
import ir.dicode.ping.data.SourceDefinition
import ir.dicode.ping.databinding.DialogAppBypassBinding
import ir.dicode.ping.databinding.DialogSourceBinding
import ir.dicode.ping.databinding.FragmentSettingsBinding
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.text.Collator
import java.util.Locale

class SettingsFragment : Fragment() {
    private var _binding: FragmentSettingsBinding? = null
    private val binding get() = _binding!!
    private val vm: MainViewModel by activityViewModels()
    private lateinit var sourceAdapter: SourceAdapter

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?,
    ): View = FragmentSettingsBinding.inflate(inflater, container, false).also { _binding = it }.root

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        val store = vm.repo.settings
        setupTabs()
        setupAppearance()

        binding.mode.check(if (store.connectionMode == "manual") R.id.modeManual else R.id.modeAuto)
        binding.mode.addOnButtonCheckedListener { _, id, checked ->
            if (checked) vm.repo.setConnectionMode(if (id == R.id.modeManual) "manual" else "auto")
        }

        binding.bypassDomains.setText(store.bypassDomains)
        updateBypassAppsSummary()
        binding.chooseBypassApps.setOnClickListener { showBypassAppsDialog() }
        binding.saveBypass.setOnClickListener {
            store.bypassDomains = normalizeDomains(binding.bypassDomains.text?.toString().orEmpty())
            binding.bypassDomains.setText(store.bypassDomains)
            binding.bypassDomains.setSelection(binding.bypassDomains.text?.length ?: 0)
            Snackbar.make(binding.root, R.string.settings_saved, Snackbar.LENGTH_SHORT).show()
        }

        sourceAdapter = SourceAdapter(
            onEdit = ::editSource,
            onToggle = { source, enabled -> vm.repo.updateSource(source.copy(enabled = enabled)) },
            onDelete = { vm.repo.removeSource(it.id) },
            onMove = { source, direction -> vm.repo.moveSource(source.id, direction) },
        )
        binding.sourceList.layoutManager = LinearLayoutManager(requireContext())
        binding.sourceList.adapter = sourceAdapter
        binding.addSource.setOnClickListener { editSource(null) }
        viewLifecycleOwner.lifecycleScope.launch {
            vm.repo.sources.collect { sourceAdapter.items = it }
        }
    }

    private fun setupTabs() {
        val titles = listOf(
            R.string.settings_connection,
            R.string.settings_bypass,
            R.string.settings_sources,
            R.string.settings_appearance,
        )
        titles.forEach { binding.settingsTabs.addTab(binding.settingsTabs.newTab().setText(it)) }
        binding.settingsTabs.addOnTabSelectedListener(object : TabLayout.OnTabSelectedListener {
            override fun onTabSelected(tab: TabLayout.Tab) = showSection(tab.position)
            override fun onTabUnselected(tab: TabLayout.Tab) = Unit
            override fun onTabReselected(tab: TabLayout.Tab) = Unit
        })
        showSection(0)
    }

    private fun showSection(position: Int) {
        binding.connectionSection.visibility = if (position == 0) View.VISIBLE else View.GONE
        binding.bypassSection.visibility = if (position == 1) View.VISIBLE else View.GONE
        binding.sourcesSection.visibility = if (position == 2) View.VISIBLE else View.GONE
        binding.appearanceSection.visibility = if (position == 3) View.VISIBLE else View.GONE
    }

    private fun setupAppearance() {
        val store = vm.repo.settings
        binding.language.setAdapter(
            ArrayAdapter(
                requireContext(),
                R.layout.item_dropdown,
                R.id.dropdownText,
                listOf("فارسی", "English", "System"),
            )
        )
        binding.language.setText(
            when (store.language) {
                "en" -> "English"
                "system" -> "System"
                else -> "فارسی"
            },
            false,
        )
        binding.theme.setAdapter(
            ArrayAdapter(
                requireContext(),
                R.layout.item_dropdown,
                R.id.dropdownText,
                listOf(getString(R.string.dark), getString(R.string.light), getString(R.string.system_default)),
            )
        )
        binding.theme.setText(
            when (store.theme) {
                "light" -> getString(R.string.light)
                "system" -> getString(R.string.system_default)
                else -> getString(R.string.dark)
            },
            false,
        )
        binding.language.setOnItemClickListener { _, _, position, _ ->
            store.language = when (position) {
                1 -> "en"
                2 -> "system"
                else -> "fa"
            }
            requireActivity().recreate()
        }
        binding.theme.setOnItemClickListener { _, _, position, _ ->
            store.theme = when (position) {
                1 -> "light"
                2 -> "system"
                else -> "dark"
            }
            AppCompatDelegate.setDefaultNightMode(
                when (store.theme) {
                    "light" -> AppCompatDelegate.MODE_NIGHT_NO
                    "dark" -> AppCompatDelegate.MODE_NIGHT_YES
                    else -> AppCompatDelegate.MODE_NIGHT_FOLLOW_SYSTEM
                }
            )
        }
    }


    private fun updateBypassAppsSummary() {
        val count = vm.repo.settings.bypassApps.size
        binding.bypassAppsCount.text = resources.getQuantityString(
            R.plurals.bypass_apps_count,
            count,
            count,
        )
    }

    private fun showBypassAppsDialog() {
        val dialogBinding = DialogAppBypassBinding.inflate(layoutInflater)
        val selected = vm.repo.settings.bypassApps.toMutableSet()
        val adapter = InstalledAppAdapter(selected) { count ->
            dialogBinding.selectedCount.text = resources.getQuantityString(
                R.plurals.bypass_apps_count,
                count,
                count,
            )
        }
        dialogBinding.appList.layoutManager = LinearLayoutManager(requireContext())
        dialogBinding.appList.adapter = adapter
        dialogBinding.appList.itemAnimator = null
        dialogBinding.selectedCount.text = resources.getQuantityString(
            R.plurals.bypass_apps_count,
            selected.size,
            selected.size,
        )

        val dialog = MaterialAlertDialogBuilder(requireContext())
            .setTitle(R.string.bypass_apps_title)
            .setMessage(R.string.bypass_apps_dialog_help)
            .setView(dialogBinding.root)
            .setNegativeButton(android.R.string.cancel, null)
            .setPositiveButton(R.string.save, null)
            .create()

        var allApps: List<InstalledAppEntry> = emptyList()
        fun filterApps(query: String) {
            val value = query.trim()
            val filtered = if (value.isBlank()) allApps else allApps.filter {
                it.label.contains(value, ignoreCase = true) ||
                    it.packageName.contains(value, ignoreCase = true)
            }
            adapter.submitList(filtered)
            dialogBinding.appEmpty.visibility = if (filtered.isEmpty() && allApps.isNotEmpty()) {
                View.VISIBLE
            } else {
                View.GONE
            }
        }

        dialog.setOnShowListener {
            dialog.getButton(android.app.AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                vm.repo.settings.bypassApps = selected
                updateBypassAppsSummary()
                Snackbar.make(binding.root, R.string.settings_saved, Snackbar.LENGTH_SHORT).show()
                dialog.dismiss()
            }
            val appContext = requireContext().applicationContext
            viewLifecycleOwner.lifecycleScope.launch {
                allApps = withContext(Dispatchers.IO) { loadLaunchableApps(appContext) }
                if (!isAdded || _binding == null || !dialog.isShowing) return@launch
                dialogBinding.appSkeleton.visibility = View.GONE
                dialogBinding.appList.visibility = View.VISIBLE
                filterApps(dialogBinding.appSearch.text?.toString().orEmpty())
            }
        }
        dialog.setOnDismissListener { adapter.dispose() }
        dialogBinding.appSearch.doAfterTextChanged { filterApps(it?.toString().orEmpty()) }
        dialog.show()
    }

    private fun loadLaunchableApps(context: Context): List<InstalledAppEntry> {
        val pm = context.packageManager
        val launcherIntent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        val activities = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            pm.queryIntentActivities(
                launcherIntent,
                PackageManager.ResolveInfoFlags.of(PackageManager.MATCH_ALL.toLong()),
            )
        } else {
            @Suppress("DEPRECATION")
            pm.queryIntentActivities(launcherIntent, PackageManager.MATCH_ALL)
        }
        val collator = Collator.getInstance(
            if (vm.repo.settings.language == "fa") Locale("fa") else Locale.getDefault(),
        )
        return activities.asSequence()
            .filter { it.activityInfo.packageName != context.packageName }
            .distinctBy { it.activityInfo.packageName }
            .mapNotNull { info ->
                runCatching {
                    InstalledAppEntry(
                        packageName = info.activityInfo.packageName,
                        label = info.loadLabel(pm).toString().ifBlank { info.activityInfo.packageName },
                    )
                }.getOrNull()
            }
            .sortedWith { first, second -> collator.compare(first.label, second.label) }
            .toList()
    }

    private fun normalizeDomains(raw: String): String = raw
        .lineSequence()
        .flatMap { line -> line.split(',', ';', ' ', '\t').asSequence() }
        .map { it.trim().removePrefix("https://").removePrefix("http://").substringBefore('/') }
        .filter { it.isNotBlank() }
        .distinct()
        .take(200)
        .joinToString("\n")

    private fun editSource(source: SourceDefinition?) {
        val dialogBinding = DialogSourceBinding.inflate(layoutInflater)
        dialogBinding.name.setText(source?.name.orEmpty())
        dialogBinding.url.setText(source?.url.orEmpty())
        dialogBinding.url.isEnabled = source?.isDefault != true

        val dialog = MaterialAlertDialogBuilder(requireContext())
            .setTitle(if (source == null) R.string.add_source else R.string.edit_source)
            .setView(dialogBinding.root)
            .setNegativeButton(android.R.string.cancel, null)
            .setPositiveButton(R.string.save, null)
            .create()
        dialog.setOnShowListener {
            dialog.getButton(android.app.AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                val name = dialogBinding.name.text.toString().trim()
                val url = dialogBinding.url.text.toString().trim()
                if (name.isBlank() || !url.startsWith("https://")) {
                    dialogBinding.urlLayout.error = getString(R.string.invalid_source)
                    return@setOnClickListener
                }
                if (source == null) vm.repo.addSource(name, url)
                else vm.repo.updateSource(source.copy(name = name))
                dialog.dismiss()
            }
        }
        dialog.show()
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
