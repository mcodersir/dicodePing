package com.v2ray.ang.ui.main

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.URL

internal data class SponsorAd(val title: String, val body: String, val url: String, val imageUrl: String? = null)
internal fun parseSponsor(json: String, placement: String, fa: Boolean): SponsorAd? = runCatching {
    require(json.length <= 131072 && placement in setOf("home", "profiles", "fox"))
    val root = JSONObject(json)
    if (root.optInt("version") != 1 || !root.optBoolean("enabled") || root.optJSONObject("placements")?.optBoolean(placement) != true) return null
    val ads = root.optJSONArray("ads") ?: return null
    for (i in 0 until minOf(ads.length(), 20)) {
        val ad = ads.optJSONObject(i) ?: continue
        val positions = ad.optJSONArray("placements") ?: continue
        if (!ad.optBoolean("enabled") || (0 until positions.length()).none { positions.optString(it) == placement }) continue
        val url = ad.optString("target_url"); val uri = java.net.URI(url)
        val host = uri.host ?: continue
        if (url.length > 2048 || uri.scheme != "https" || uri.userInfo != null || '.' !in host || host.startsWith("127.") || host == "localhost") continue
        val title = ad.optString(if (fa) "title_fa" else "title_en")
        val body = ad.optString(if (fa) "body_fa" else "body_en")
        if (title.isBlank() || title.length > 120 || body.length > 400) continue
        val image = ad.optString("image_url").takeIf { ad.optString("type") == "banner" && it.isNotBlank() }
        if (image != null) {
            val picture = java.net.URI(image); val pictureHost = picture.host ?: continue
            if (image.length > 2048 || picture.scheme != "https" || picture.userInfo != null || '.' !in pictureHost || pictureHost.startsWith("127.") || pictureHost == "localhost") continue
        }
        return SponsorAd(title, body, url, image)
    }
    null
}.getOrNull()

@Composable
internal fun SponsorBanner(placement: String) {
    val context = LocalContext.current
    val fa = context.resources.configuration.locales[0].language == "fa"
    var ad by remember(placement) { mutableStateOf<SponsorAd?>(null) }
    LaunchedEffect(placement, fa) {
        while (true) {
            ad = withContext(Dispatchers.IO) { runCatching {
                val c = URL("https://raw.githubusercontent.com/mcodersir/dicodePing/refs/heads/main/ads.txt").openConnection() as java.net.HttpURLConnection
                c.connectTimeout = 4000; c.readTimeout = 4000; c.instanceFollowRedirects = false
                try { if (c.responseCode != 200) null else { val b = c.inputStream.use { input -> val out = java.io.ByteArrayOutputStream(); val chunk = ByteArray(4096)
                    while (out.size() <= 131072) { val count = input.read(chunk, 0, minOf(chunk.size, 131073 - out.size())); if (count < 0) break; out.write(chunk, 0, count) }; out.toByteArray() }; if (b.size > 131072) null else parseSponsor(b.toString(Charsets.UTF_8), placement, fa) } } finally { c.disconnect() }
            }.getOrNull() }
            delay(15 * 60_000L)
        }
    }
    ad?.let { sponsor ->
        OutlinedCard(onClick = { runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(sponsor.url))) } },
            modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp)) {
            Column(Modifier.padding(horizontal = 10.dp, vertical = 6.dp)) {
                Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(if (fa) "تبلیغ" else "Ad", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(sponsor.title, style = MaterialTheme.typography.labelLarge, modifier = Modifier.weight(1f), maxLines = 1, overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis)
                    Text("↗", style = MaterialTheme.typography.labelMedium)
                }
                if (sponsor.imageUrl != null) {
                    var bitmap by remember(sponsor.imageUrl) { mutableStateOf<androidx.compose.ui.graphics.ImageBitmap?>(null) }
                    LaunchedEffect(sponsor.imageUrl) {
                        bitmap = withContext(Dispatchers.IO) { runCatching {
                            val c = URL(sponsor.imageUrl).openConnection() as java.net.HttpURLConnection
                            c.connectTimeout = 4000; c.readTimeout = 4000; c.instanceFollowRedirects = false
                            try {
                                require(c.responseCode == 200)
                                val bytes = c.inputStream.use { input ->
                                    val out = java.io.ByteArrayOutputStream(); val buffer = ByteArray(4096)
                                    while (true) { val n = input.read(buffer); if (n < 0) break; require(out.size() + n <= 1048576); out.write(buffer, 0, n) }; out.toByteArray()
                                }
                                val options = android.graphics.BitmapFactory.Options().apply { inJustDecodeBounds = true }
                                android.graphics.BitmapFactory.decodeByteArray(bytes, 0, bytes.size, options)
                                require(options.outWidth in 1..4096 && options.outHeight in 1..4096)
                                options.inJustDecodeBounds = false
                                android.graphics.BitmapFactory.decodeByteArray(bytes, 0, bytes.size, options)?.asImageBitmap()
                            } finally { c.disconnect() }
                        }.getOrNull() }
                    }
                    bitmap?.let { androidx.compose.foundation.Image(it, sponsor.title, Modifier.fillMaxWidth().heightIn(max = 88.dp), contentScale = androidx.compose.ui.layout.ContentScale.Fit) }
                } else if (sponsor.body.isNotBlank()) {
                    Text(sponsor.body, style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis)
                }
            }
        }
    }
}
