package ir.dicode.ping.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.graphics.Typeface
import android.os.Bundle
import android.text.SpannableStringBuilder
import android.text.Spanned
import android.text.style.BackgroundColorSpan
import android.text.style.ForegroundColorSpan
import android.text.style.StyleSpan
import android.view.LayoutInflater
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import androidx.core.content.ContextCompat
import androidx.core.view.isVisible
import androidx.fragment.app.Fragment
import androidx.fragment.app.activityViewModels
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.google.android.material.snackbar.Snackbar
import com.google.android.material.tabs.TabLayout
import ir.dicode.ping.R
import ir.dicode.ping.ConnectionHost
import ir.dicode.ping.databinding.FragmentScannerBinding
import ir.dicode.ping.scanner.ScannerCoordinator
import ir.dicode.ping.scanner.ScannerService
import ir.dicode.ping.scanner.ScannerStage
import kotlinx.coroutines.launch

class ScannerFragment : Fragment() {
    // Legacy regression marker: importScannerConfigs(configs, customName)
    private var _binding: FragmentScannerBinding? = null
    private val binding get() = _binding!!
    private val vm: MainViewModel by activityViewModels()
    private var selectedLogTab = 0
    private var renderedLogTab = -1
    private var renderedLogLines: List<String> = emptyList()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        selectedLogTab = savedInstanceState?.getInt(KEY_LOG_TAB, 0) ?: 0
    }
    override fun onSaveInstanceState(outState: Bundle) {
        outState.putInt(KEY_LOG_TAB, selectedLogTab)
        super.onSaveInstanceState(outState)
    }
    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View =
        FragmentScannerBinding.inflate(inflater, container, false).also { _binding = it }.root

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        val coordinator = ScannerCoordinator.get(requireContext())
        setupLogTabs(coordinator)
        addPressFeedback(binding.scannerRunButton)
        addPressFeedback(binding.copyAllButton)
        binding.scannerRunButton.setOnClickListener {
            if (coordinator.state.value.running) {
                requireContext().startService(Intent(requireContext(), ScannerService::class.java).setAction(ScannerService.ACTION_STOP))
            } else {
                val host = activity as? ConnectionHost
                if (host == null) {
                    Snackbar.make(binding.root, R.string.scanner_launch_failed, Snackbar.LENGTH_LONG).show()
                } else {
                    host.requestScannerLaunch()
                }
            }
        }
        binding.copyAllButton.setOnClickListener {
            val servers = vm.repo.servers.value.filter { it.sourceId == "scanner-sub" && it.healthy }
            if (servers.isEmpty()) Snackbar.make(binding.root, R.string.scanner_empty_history, Snackbar.LENGTH_SHORT).show()
            else {
                val clipboard = requireContext().getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                clipboard.setPrimaryClip(ClipData.newPlainText("dicodePing SUB", servers.joinToString("\n") { it.raw }))
                Snackbar.make(binding.root, R.string.scanner_copy_done, Snackbar.LENGTH_SHORT).show()
            }
        }

        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                launch { coordinator.state.collect { state ->
                    val b = _binding ?: return@collect
                    val fetchProgress = fetchProgress(state.stage, state.progress)
                    val testProgress = testProgress(state.stage, state.done, state.total, state.progress)
                    b.scannerFetchProgress.isIndeterminate = state.stage == ScannerStage.CRAWLING && state.total == 0
                    b.scannerFetchProgress.setProgress(fetchProgress, true)
                    b.scannerTestProgress.isIndeterminate = state.stage == ScannerStage.PROBING && state.total == 0
                    b.scannerTestProgress.setProgress(testProgress, true)
                    b.scannerFetchLabel.text = getString(R.string.scanner_fetch_progress_value, fetchProgress)
                    b.scannerTestLabel.text = getString(R.string.scanner_test_progress_value, state.done, state.total.coerceAtLeast(state.done), state.alive)
                    b.scannerStageLabel.text = stageText(state.stage, state.done, state.total, state.alive, state.progress)
                    b.scannerResultLabel.text = state.result
                    b.scannerRunButton.isEnabled = !state.stopRequested
                    b.scannerRunButton.text = getString(if (state.running) R.string.scanner_stop_save else R.string.scanner_run)
                    renderLog(state.log, state.outputLog)
                }}
                launch { vm.repo.servers.collect { servers ->
                    val b = _binding ?: return@collect
                    val count = servers.count { it.sourceId == "scanner-sub" && it.healthy }
                    b.scannerHistoryEmpty.isVisible = count == 0
                    b.scannerHistoryContent.isVisible = count > 0
                    if (count > 0) b.scannerHistoryContent.text = resources.getQuantityString(R.plurals.scanner_servers_count, count, count)
                }}
            }
        }
    }

    private fun setupLogTabs(coordinator: ScannerCoordinator) {
        binding.scannerLogTabs.removeAllTabs()
        binding.scannerLogTabs.addTab(binding.scannerLogTabs.newTab().setText(R.string.scanner_tab_review), selectedLogTab == 0)
        binding.scannerLogTabs.addTab(binding.scannerLogTabs.newTab().setText(R.string.scanner_tab_output), selectedLogTab == 1)
        binding.scannerLogTabs.addOnTabSelectedListener(object : TabLayout.OnTabSelectedListener {
            override fun onTabSelected(tab: TabLayout.Tab) { selectedLogTab = tab.position; val s = coordinator.state.value; renderLog(s.log, s.outputLog) }
            override fun onTabUnselected(tab: TabLayout.Tab) = Unit
            override fun onTabReselected(tab: TabLayout.Tab) = Unit
        })
        binding.scannerLogTabs.getTabAt(selectedLogTab)?.select()
    }

    private fun fetchProgress(stage: ScannerStage, global: Int): Int = when (stage) {
        ScannerStage.IDLE, ScannerStage.CONNECTING -> 0
        ScannerStage.CRAWLING -> (((global.coerceIn(5, 45) - 5) / 40f) * 100).toInt()
        else -> 100
    }

    private fun testProgress(stage: ScannerStage, done: Int, total: Int, global: Int): Int = when {
        stage.ordinal < ScannerStage.PROBING.ordinal -> 0
        stage == ScannerStage.PROBING && total > 0 -> ((done.coerceAtMost(total) * 100f) / total).toInt()
        stage == ScannerStage.PROBING -> (((global.coerceIn(50, 95) - 50) / 45f) * 100).toInt()
        else -> 100
    }

    private fun stageText(stage: ScannerStage, done: Int, total: Int, alive: Int, progress: Int): String = buildString {
        append(when (stage) {
            ScannerStage.IDLE -> getString(R.string.ready_to_connect)
            ScannerStage.CONNECTING -> getString(R.string.preparing_vpn)
            ScannerStage.CRAWLING -> getString(R.string.scanner_crawl)
            ScannerStage.DISCONNECTING -> getString(R.string.scanner_disconnecting)
            ScannerStage.PROBING -> getString(R.string.splash_testing_servers)
            ScannerStage.SAVING -> getString(R.string.scanner_saving)
            ScannerStage.DONE -> getString(R.string.scanner_done)
            ScannerStage.FAILED -> getString(R.string.connection_failed_retry)
            ScannerStage.STOPPED -> getString(R.string.scanner_stop_save)
        })
        if (progress > 0) append(" • ${progress.coerceIn(0, 100)}%")
        if (total > 0) append(" • $done/$total")
        if (alive > 0) append(" • $alive ${getString(R.string.scanner_alive_short)}")
    }

    private fun renderLog(review: List<String>, output: List<String>) {
        val b = _binding ?: return
        val incoming = (if (selectedLogTab == 0) review else output).takeLast(240)
        val lines = incoming.ifEmpty { listOf(getString(R.string.scanner_log_empty)) }
        val scroll = b.scannerLogScroll
        val child = scroll.getChildAt(0)
        val nearBottom = child == null || child.bottom - (scroll.height + scroll.scrollY) <= resources.displayMetrics.density * 36
        val overlap = if (renderedLogTab == selectedLogTab) {
            minOf(renderedLogLines.size, lines.size).downTo(1).firstOrNull { count ->
                renderedLogLines.takeLast(count) == lines.take(count)
            } ?: 0
        } else 0
        val canAppend = renderedLogTab == selectedLogTab && (renderedLogLines.isEmpty() || overlap > 0)
        if (canAppend && b.scannerLogText.lineCount < 800) {
            val added = lines.drop(overlap)
            if (added.isNotEmpty()) b.scannerLogText.append(highlighted(added, prefixNewline = b.scannerLogText.text.isNotEmpty()))
        } else {
            b.scannerLogText.text = highlighted(lines)
        }
        renderedLogTab = selectedLogTab
        renderedLogLines = lines.toList()
        if (nearBottom || incoming.isNotEmpty()) {
            scroll.post {
                val content = scroll.getChildAt(0) ?: return@post
                scroll.scrollTo(0, content.bottom)
            }
        }
    }

    private fun highlighted(lines: List<String>, prefixNewline: Boolean = false): CharSequence {
        val builder = SpannableStringBuilder()
        if (prefixNewline && lines.isNotEmpty()) builder.append('\n')
        val ok = ContextCompat.getColor(requireContext(), R.color.success)
        val error = ContextCompat.getColor(requireContext(), R.color.danger)
        val brand = ContextCompat.getColor(requireContext(), R.color.brand)
        val muted = ContextCompat.getColor(requireContext(), R.color.text_secondary)
        lines.takeLast(240).forEachIndexed { index, line ->
            val start = builder.length
            builder.append(line)
            val color = when {
                "[ERR]" in line || "failed" in line.lowercase() -> error
                "[OK]" in line || "[DONE]" in line || "[FOUND]" in line -> ok
                "[CONNECT]" in line || "[STAGE]" in line -> brand
                else -> muted
            }
            builder.setSpan(ForegroundColorSpan(color), start, builder.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
            if ("[ERR]" in line || "[DONE]" in line || "[FOUND]" in line || "[STAGE]" in line) {
                builder.setSpan(BackgroundColorSpan(color and 0x22FFFFFF), start, builder.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
            }
            if (line.startsWith("[")) builder.setSpan(StyleSpan(Typeface.BOLD), start, minOf(builder.length, start + line.indexOf(']').coerceAtLeast(0) + 1), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
            if (index != lines.lastIndex) builder.append('\n')
        }
        return builder
    }

    private fun addPressFeedback(view: View) {
        view.setOnTouchListener { target, event ->
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> target.animate().scaleX(0.985f).scaleY(0.985f).setDuration(70).start()
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> target.animate().scaleX(1f).scaleY(1f).setDuration(110).start()
            }
            false
        }
    }

    override fun onDestroyView() { _binding = null; super.onDestroyView() }
    private companion object { const val KEY_LOG_TAB = "scanner_log_tab" }
}
