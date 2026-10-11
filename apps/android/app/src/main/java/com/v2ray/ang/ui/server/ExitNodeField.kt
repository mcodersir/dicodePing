package com.v2ray.ang.ui.server

import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.res.stringResource
import com.v2ray.ang.R
import com.v2ray.ang.core.AetherExitNode
import com.v2ray.ang.ui.compose.FormDropdownField

/**
 * The exit-node an Aether core dials out through, in the Aether editor and on the WARP keys page alike: freedom, the
 * default, with the finalMask and the dialMode set beside it, or one of [nodes], the names of the profiles a chain
 * takes for a hop, whose outbound then is the exit-node. [value] is the name chosen, blank for freedom; a name no
 * profile has any more, or several have, shows with the message that says so. [nodes] is null until they are read.
 */
@Composable
internal fun ExitNodeField(
    value: String,
    nodes: List<AetherExitNode>?,
    onValueChange: (String) -> Unit,
    enabled: Boolean = true,
) {
    val freedom = stringResource(R.string.aether_exit_node_freedom)
    val numbered = stringResource(R.string.label_numbered)
    val names = nodes.orEmpty().map { it.name }
    val labels = remember(names, freedom, numbered) { distinctLabels(names, setOf(freedom)) { name, number -> numbered.format(name, number) } }
    val name = value.trim()
    val problem = problemOfExitNode(name, nodes)
    FormDropdownField(
        label = stringResource(R.string.aether_lab_exit_node),
        // The label the list gives the name, which tells it from freedom and from another name's label.
        value = if (name.isEmpty()) freedom else labels.getOrNull(names.indexOf(name)) ?: name,
        options = listOf(freedom) + labels,
        onValueChange = { picked ->
            if (picked == freedom) {
                onValueChange("")
            } else {
                labels.indexOf(picked).takeIf { it >= 0 }?.let { onValueChange(names[it]) }
            }
        },
        enabled = enabled,
        supportingText = when {
            name.isEmpty() -> null
            problem != null -> stringResource(problem.message, name)
            else -> stringResource(R.string.aether_hint_exit_node)
        },
    )
}
