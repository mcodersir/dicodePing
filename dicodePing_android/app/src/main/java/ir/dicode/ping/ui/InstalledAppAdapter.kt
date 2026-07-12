package ir.dicode.ping.ui

import android.graphics.drawable.Drawable
import android.util.LruCache
import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import ir.dicode.ping.databinding.ItemInstalledAppBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class InstalledAppEntry(
    val packageName: String,
    val label: String,
)

class InstalledAppAdapter(
    private val selected: MutableSet<String>,
    private val onSelectionChanged: (Int) -> Unit,
) : ListAdapter<InstalledAppEntry, InstalledAppAdapter.Holder>(DIFF) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val iconCache = LruCache<String, Drawable.ConstantState>(24)

    inner class Holder(val binding: ItemInstalledAppBinding) : RecyclerView.ViewHolder(binding.root) {
        var iconJob: Job? = null
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int) = Holder(
        ItemInstalledAppBinding.inflate(LayoutInflater.from(parent.context), parent, false),
    )

    override fun onBindViewHolder(holder: Holder, position: Int) {
        val item = getItem(position)
        val context = holder.binding.root.context
        val pm = context.packageManager
        with(holder.binding) {
            appIcon.setImageDrawable(pm.defaultActivityIcon)
            appName.text = item.label
            appPackage.text = item.packageName
            appCheck.setOnCheckedChangeListener(null)
            appCheck.isChecked = item.packageName in selected

            holder.iconJob?.cancel()
            val cached = iconCache.get(item.packageName)
            if (cached != null) {
                appIcon.setImageDrawable(cached.newDrawable(context.resources))
            } else {
                holder.iconJob = scope.launch {
                    val state = withContext(Dispatchers.IO) {
                        runCatching { pm.getApplicationIcon(item.packageName).constantState }.getOrNull()
                    }
                    if (state != null) iconCache.put(item.packageName, state)
                    val current = holder.bindingAdapterPosition
                    if (current != RecyclerView.NO_POSITION && getItem(current).packageName == item.packageName) {
                        appIcon.setImageDrawable(state?.newDrawable(context.resources) ?: pm.defaultActivityIcon)
                    }
                }
            }

            fun toggle() {
                if (item.packageName in selected) selected.remove(item.packageName)
                else selected.add(item.packageName)
                val current = holder.bindingAdapterPosition
                if (current != RecyclerView.NO_POSITION) notifyItemChanged(current)
                onSelectionChanged(selected.size)
            }

            root.setOnClickListener { toggle() }
            appCheck.setOnClickListener { toggle() }
        }
    }

    override fun onViewRecycled(holder: Holder) {
        holder.iconJob?.cancel()
        holder.iconJob = null
        super.onViewRecycled(holder)
    }

    fun dispose() = scope.cancel()

    companion object {
        private val DIFF = object : DiffUtil.ItemCallback<InstalledAppEntry>() {
            override fun areItemsTheSame(oldItem: InstalledAppEntry, newItem: InstalledAppEntry) =
                oldItem.packageName == newItem.packageName

            override fun areContentsTheSame(oldItem: InstalledAppEntry, newItem: InstalledAppEntry) =
                oldItem.packageName == newItem.packageName && oldItem.label == newItem.label
        }
    }
}
