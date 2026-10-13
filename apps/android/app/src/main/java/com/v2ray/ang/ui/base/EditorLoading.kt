package com.v2ray.ang.ui.base

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Scaffold
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.v2ray.ang.ui.compose.AppTopBar

/**
 * PattNG: an editor screen while what it opens on is read off the main thread, see [EditorViewModel.openedWith]: its top
 * bar, titled [title], with Back, which [onBackClick] takes, and the bar's progress line.
 */
@Composable
fun EditorLoading(title: String, onBackClick: () -> Unit) {
    Scaffold(
        contentWindowInsets = WindowInsets(0),
        topBar = { AppTopBar(title = title, onBackClick = onBackClick, isLoading = true) }
    ) { innerPadding ->
        Box(Modifier.fillMaxSize().padding(innerPadding))
    }
}
