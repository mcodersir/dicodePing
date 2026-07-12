package ir.dicode.ping.ui

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.core.content.FileProvider
import androidx.fragment.app.Fragment
import com.google.android.material.snackbar.Snackbar
import ir.dicode.ping.BuildConfig
import ir.dicode.ping.R
import ir.dicode.ping.databinding.FragmentAboutBinding
import ir.dicode.ping.util.AppLog

class AboutFragment : Fragment() {
    private var _binding: FragmentAboutBinding? = null
    private val binding get() = _binding!!

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?,
    ): View = FragmentAboutBinding.inflate(inflater, container, false).also { _binding = it }.root

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        binding.version.text = BuildConfig.VERSION_NAME
        binding.github.setOnClickListener { open("https://github.com/mcodersir/") }
        binding.telegram.setOnClickListener { open("https://t.me/dicodeping") }
        binding.shareLogs.setOnClickListener { shareLogs() }
        binding.clearLogs.setOnClickListener {
            AppLog.clear(requireContext())
            Snackbar.make(binding.root, R.string.logs_cleared, Snackbar.LENGTH_SHORT).show()
        }
    }

    private fun shareLogs() {
        runCatching {
            val file = AppLog.exportSnapshot(requireContext())
            val uri = FileProvider.getUriForFile(
                requireContext(),
                "${BuildConfig.APPLICATION_ID}.files",
                file,
            )
            startActivity(
                Intent.createChooser(
                    Intent(Intent.ACTION_SEND).apply {
                        type = "text/plain"
                        putExtra(Intent.EXTRA_STREAM, uri)
                        putExtra(Intent.EXTRA_SUBJECT, "dicodePing diagnostic log")
                        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    },
                    getString(R.string.share_logs),
                )
            )
        }.onFailure {
            AppLog.e("About", "Could not share diagnostic log", it)
            Snackbar.make(binding.root, R.string.log_share_failed, Snackbar.LENGTH_LONG).show()
        }
    }

    private fun open(url: String) = startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
