package com.v2ray.ang.ui.base

import androidx.activity.compose.BackHandler
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.v2ray.ang.R
import com.v2ray.ang.extension.toast
import com.v2ray.ang.extension.toastSuccess

/**
 * PattNG: acts once on each outcome of [viewModel], in whichever activity shows the editor when it comes: tells a
 * refusal; tells a save, then hands the key it stored as to [onSaved]; hands a delete to [onDeleted]. The outcome is
 * cleared first, so that the screen may close on it, see [EditorViewModel.leaveScreen]. Back waits while a save or a
 * delete runs, or the outcome it closes on is still to be acted on, as the activity's finish() does: held only meanwhile,
 * so that predictive back shows where it leads at any other time.
 */
@Composable
fun EditorOutcomeEffect(
    viewModel: EditorViewModel,
    onSaved: (key: String) -> Unit,
    onDeleted: () -> Unit = {},
) {
    val busy by viewModel.busy.collectAsStateWithLifecycle()
    val outcome by viewModel.outcome.collectAsStateWithLifecycle()
    BackHandler(enabled = busy || outcome.closesScreen) {}
    val context = LocalContext.current
    LaunchedEffect(outcome) {
        val result = outcome ?: return@LaunchedEffect
        viewModel.onOutcomeHandled(result)
        when (result) {
            is EditorOutcome.Refused -> context.toast(
                if (result.args.isEmpty()) context.getString(result.message)
                else context.getString(result.message, *result.args.toTypedArray())
            )

            is EditorOutcome.Saved -> {
                context.toastSuccess(R.string.toast_success)
                onSaved(result.key)
            }

            EditorOutcome.Deleted -> onDeleted()
        }
    }
}
