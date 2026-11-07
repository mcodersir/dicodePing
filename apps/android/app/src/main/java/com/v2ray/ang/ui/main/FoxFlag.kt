package com.v2ray.ang.ui.main

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp

@Composable internal fun FoxFlag(code: String) {
    val context = LocalContext.current
    val bitmap = remember(code) { if (code.length == 2 && code.all { it.isLetter() }) runCatching { context.assets.open("flags/${code.lowercase(java.util.Locale.ROOT)}.png").use { BitmapFactory.decodeStream(it).asImageBitmap() } }.getOrNull() else null }
    if (bitmap != null) Image(bitmap, contentDescription = code, modifier = Modifier.size(30.dp, 20.dp).clip(RoundedCornerShape(4.dp)))
    else Text("◎", modifier = Modifier.width(30.dp))
}
