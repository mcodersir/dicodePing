package ir.dicode.ping.ui

import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.RecyclerView
import ir.dicode.ping.data.SourceDefinition
import ir.dicode.ping.databinding.ItemSourceBinding

class SourceAdapter(
    private val onEdit: (SourceDefinition) -> Unit,
    private val onToggle: (SourceDefinition, Boolean) -> Unit,
    private val onDelete: (SourceDefinition) -> Unit,
    private val onMove: (SourceDefinition, Int) -> Unit,
) : RecyclerView.Adapter<SourceAdapter.H>() {
    var items: List<SourceDefinition> = emptyList()
        set(value) {
            val old = field
            field = value
            DiffUtil.calculateDiff(object : DiffUtil.Callback() {
                override fun getOldListSize() = old.size
                override fun getNewListSize() = value.size
                override fun areItemsTheSame(oldItemPosition: Int, newItemPosition: Int) =
                    old[oldItemPosition].id == value[newItemPosition].id
                override fun areContentsTheSame(oldItemPosition: Int, newItemPosition: Int) =
                    old[oldItemPosition] == value[newItemPosition]
            }).dispatchUpdatesTo(this)
        }

    inner class H(val binding: ItemSourceBinding) : RecyclerView.ViewHolder(binding.root)

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int) = H(
        ItemSourceBinding.inflate(LayoutInflater.from(parent.context), parent, false),
    )

    override fun getItemCount() = items.size

    override fun onBindViewHolder(holder: H, position: Int) {
        val source = items[position]
        with(holder.binding) {
            name.text = source.name
            url.text = if (source.url.isBlank()) root.context.getString(ir.dicode.ping.R.string.local_scanner_output) else source.url
            enabled.setOnCheckedChangeListener(null)
            enabled.isChecked = source.enabled
            enabled.isEnabled = !source.isDefault
            delete.isEnabled = !source.isDefault
            up.isEnabled = position > 0
            down.isEnabled = position < items.lastIndex
            edit.setOnClickListener { onEdit(source) }
            enabled.setOnCheckedChangeListener { _, checked -> onToggle(source, checked) }
            delete.setOnClickListener { onDelete(source) }
            up.setOnClickListener { onMove(source, -1) }
            down.setOnClickListener { onMove(source, 1) }
        }
    }
}
