package ir.dicode.ping.ui

import android.graphics.drawable.GradientDrawable
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.view.animation.AlphaAnimation
import android.view.animation.Animation
import androidx.core.content.ContextCompat
import androidx.core.graphics.ColorUtils
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import ir.dicode.ping.R
import ir.dicode.ping.data.ServerRecord
import ir.dicode.ping.data.ServerPolicy
import ir.dicode.ping.databinding.ItemServerBinding
import ir.dicode.ping.util.PublicServerLabel
import java.util.Locale

class ServerAdapter(
    private val selected: () -> String,
    private val onSelect: (ServerRecord) -> Unit,
    private val onConnect: (ServerRecord) -> Unit,
    private val onFavorite: (ServerRecord) -> Unit,
    private val interactionLocked: () -> Boolean,
    private val onLocked: () -> Unit,
    private val onRestricted: () -> Unit,
) : ListAdapter<ServerRecord, ServerAdapter.Holder>(object : DiffUtil.ItemCallback<ServerRecord>() {
    override fun areItemsTheSame(oldItem: ServerRecord, newItem: ServerRecord) = oldItem.id == newItem.id
    override fun areContentsTheSame(oldItem: ServerRecord, newItem: ServerRecord) = oldItem == newItem
}) {
    init {
        setHasStableIds(true)
    }

    override fun getItemId(position: Int): Long = getItem(position).id.hashCode().toLong()

    inner class Holder(val binding: ItemServerBinding) : RecyclerView.ViewHolder(binding.root)

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int) = Holder(
        ItemServerBinding.inflate(LayoutInflater.from(parent.context), parent, false)
    )

    override fun onBindViewHolder(holder: Holder, position: Int) {
        val server = getItem(position)
        with(holder.binding) {
            val context = root.context
            val isSelected = server.id == selected()
            val locked = interactionLocked()
            val restricted = ServerPolicy.isRestricted(server)
            val fallback = server.city.ifBlank {
                server.country.ifBlank { context.getString(R.string.generic_server) }
            }

            serverFlag.text = flag(server.countryCode).ifBlank { "🌐" }
            serverName.text = PublicServerLabel.name(server.name, fallback)
            location.text = listOf(server.city, server.region, server.country)
                .filter { it.isNotBlank() }
                .distinct()
                .joinToString(" • ")
                .ifBlank { context.getString(R.string.server_details) }

            network.visibility = View.GONE

            bindPing(this, server)
            selectedBadge.visibility = if (isSelected) View.VISIBLE else View.INVISIBLE
            root.strokeWidth = dp(root, if (isSelected) 2 else 1)
            root.strokeColor = ContextCompat.getColor(
                context,
                if (isSelected) R.color.brand else R.color.outline_soft,
            )

            favorite.setIconResource(
                if (server.favorite) R.drawable.ic_star_filled else R.drawable.ic_star_outline,
            )
            favorite.contentDescription = context.getString(R.string.favorite_server)

            root.alpha = if ((locked && !isSelected) || restricted) 0.62f else 1f
            connect.isEnabled = !locked && !restricted
            connect.alpha = if (locked || restricted) 0.55f else 1f
            connect.text = context.getString(
                if (restricted) R.string.server_disabled else R.string.connect_selected_short,
            )

            root.setOnClickListener {
                if (restricted) {
                    onRestricted()
                    return@setOnClickListener
                }
                if (interactionLocked()) {
                    onLocked()
                    return@setOnClickListener
                }
                val previous = currentList.indexOfFirst { it.id == selected() }
                val current = holder.bindingAdapterPosition
                onSelect(server)
                if (previous >= 0) notifyItemChanged(previous)
                if (current != RecyclerView.NO_POSITION) notifyItemChanged(current)
            }
            connect.setOnClickListener {
                if (restricted) {
                    onRestricted()
                    return@setOnClickListener
                }
                if (interactionLocked()) {
                    onLocked()
                    return@setOnClickListener
                }
                onSelect(server)
                onConnect(server)
            }
            favorite.setOnClickListener { onFavorite(server) }
        }
    }

    private fun bindPing(binding: ItemServerBinding, server: ServerRecord) {
        val context = binding.root.context
        binding.ping.clearAnimation()
        binding.ping.alpha = 1f
        if (server.testState == ServerRecord.TEST_RUNNING) {
            val color = ContextCompat.getColor(context, R.color.brand)
            binding.ping.text = context.getString(R.string.testing_server)
            binding.ping.setTextColor(color)
            binding.ping.background = GradientDrawable().apply {
                cornerRadius = dp(binding.ping, 12).toFloat()
                setColor(ColorUtils.setAlphaComponent(color, 28))
            }
            binding.ping.startAnimation(AlphaAnimation(1f, 0.35f).apply {
                duration = 520
                repeatCount = Animation.INFINITE
                repeatMode = Animation.REVERSE
            })
            return
        }
        val (colorRes, label) = when (val delay = server.pingMs) {
            null -> R.color.text_secondary to context.getString(R.string.server_temporarily_unavailable)
            in 1..180 -> R.color.success to "$delay ms"
            in 181..350 -> R.color.warning to "$delay ms"
            else -> R.color.danger to "$delay ms"
        }
        val color = ContextCompat.getColor(context, colorRes)
        binding.ping.text = label
        binding.ping.setTextColor(color)
        binding.ping.background = GradientDrawable().apply {
            cornerRadius = dp(binding.ping, 12).toFloat()
            setColor(ColorUtils.setAlphaComponent(color, 28))
        }
    }

    override fun onViewRecycled(holder: Holder) {
        holder.binding.ping.clearAnimation()
        super.onViewRecycled(holder)
    }

    private fun dp(view: View, value: Int): Int =
        (value * view.resources.displayMetrics.density).toInt().coerceAtLeast(1)

    private fun flag(code: String): String {
        if (code.length != 2) return ""
        return code.uppercase(Locale.US).map { character ->
            String(Character.toChars(0x1F1E6 + character.code - 'A'.code))
        }.joinToString("")
    }
}
