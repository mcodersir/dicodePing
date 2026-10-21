package com.v2ray.ang.ui.main

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.URL

internal data class SponsorAd(val title: String, val body: String, val url: String)
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
        return SponsorAd(title, body, url)
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
        OutlinedCard(Modifier.fillMaxWidth().padding(8.dp)) { Column(Modifier.padding(12.dp)) {
            Text(if (fa) "تبلیغ" else "Sponsored", style = MaterialTheme.typography.labelSmall)
            Text(sponsor.title, style = MaterialTheme.typography.titleSmall)
            Text(sponsor.body, style = MaterialTheme.typography.bodySmall)
            TextButton(onClick = { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(sponsor.url))) }) { Text(if (fa) "مشاهده" else "Open") }
        } }
    }
}
