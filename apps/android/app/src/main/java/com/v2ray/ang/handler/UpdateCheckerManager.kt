package com.v2ray.ang.handler

import android.os.Build
import com.v2ray.ang.AppConfig
import com.v2ray.ang.BuildConfig
import com.v2ray.ang.dto.CheckUpdateResult
import com.v2ray.ang.dto.GitHubRelease
import com.v2ray.ang.dto.UrlContentRequest
import com.v2ray.ang.extension.concatUrl
import com.v2ray.ang.util.HttpUtil
import com.v2ray.ang.util.JsonUtil
import com.v2ray.ang.util.LogUtil
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

object UpdateCheckerManager {
    suspend fun checkForUpdate(includePreRelease: Boolean = false): CheckUpdateResult = withContext(Dispatchers.IO) {
        val url = if (includePreRelease) {
            "${AppConfig.APP_API_URL}?per_page=20"
        } else {
            AppConfig.APP_API_URL.concatUrl("latest")
        }

        val proxyUsername = SettingsManager.getSocksUsername()
        val proxyPassword = SettingsManager.getSocksPassword()

        var response = HttpUtil.getUrlContent(
            UrlContentRequest(
                url = url,
                timeout = 15000,
                userAgent = "DicodePing/${BuildConfig.VERSION_NAME}"
            )
        )
        if (response.isNullOrEmpty()) {
            val httpPort = SettingsManager.getHttpPort()
            response = HttpUtil.getUrlContent(
                UrlContentRequest(
                    url = url,
                    timeout = 15000,
                    httpPort = httpPort,
                    proxyUsername = proxyUsername,
                    proxyPassword = proxyPassword,
                    userAgent = "DicodePing/${BuildConfig.VERSION_NAME}"
                )
            )
        }

        // GitHub's `/latest` endpoint intentionally excludes prereleases and can
        // return 404 while a project is prerelease-only. Fall back to the release
        // list so the update page remains usable for every DicodePing channel.
        if (response.isNullOrEmpty() && !includePreRelease) {
            response = HttpUtil.getUrlContent(
                UrlContentRequest(
                    url = "${AppConfig.APP_API_URL}?per_page=20",
                    timeout = 15000,
                    httpPort = SettingsManager.getHttpPort(),
                    proxyUsername = proxyUsername,
                    proxyPassword = proxyPassword,
                    userAgent = "DicodePing/${BuildConfig.VERSION_NAME}"
                )
            )
            if (response.isNullOrEmpty()) {
                throw IllegalStateException("Failed to reach the update service")
            }
        }

        val latestRelease = if (includePreRelease) {
            JsonUtil.fromJsonSafe(response, Array<GitHubRelease>::class.java)
                ?.filterNot { it.draft }
                ?.maxByOrNull { it.publishedAt }
                ?: throw IllegalStateException("No release found")
        } else {
            JsonUtil.fromJsonSafe(response, GitHubRelease::class.java)
                ?: JsonUtil.fromJsonSafe(response, Array<GitHubRelease>::class.java)
                    ?.filter { !it.prerelease && !it.draft }
                    ?.maxByOrNull { it.publishedAt }
        }
        if (latestRelease == null) {
            return@withContext CheckUpdateResult(hasUpdate = false)
        }

        val latestVersion = latestRelease.tagName.removePrefix("v")
        LogUtil.i(
            AppConfig.TAG,
            "Found new version: $latestVersion (current: ${BuildConfig.VERSION_NAME})"
        )

        return@withContext if (compareVersions(latestVersion, BuildConfig.VERSION_NAME) > 0) {
            val downloadUrl = getDownloadUrl(latestRelease, Build.SUPPORTED_ABIS[0])
            CheckUpdateResult(
                hasUpdate = true,
                latestVersion = latestVersion,
                releaseNotes = latestRelease.body,
                downloadUrl = downloadUrl,
                isPreRelease = latestRelease.prerelease
            )
        } else {
            CheckUpdateResult(hasUpdate = false)
        }
    }

    private fun compareVersions(version1: String, version2: String): Int {
        // Compare all numeric segments so suffixed tags like "2.3.2-P1" work:
        // "2.3.2-P1" -> [2,3,2,1], "2.3.2" -> [2,3,2], "2.3.2-P2" > "2.3.2-P1" > "2.3.2"
        val numberRegex = Regex("\\d+")
        val v1 = numberRegex.findAll(version1).map { it.value.toInt() }.toList()
        val v2 = numberRegex.findAll(version2).map { it.value.toInt() }.toList()

        for (i in 0 until maxOf(v1.size, v2.size)) {
            val num1 = v1.getOrElse(i) { 0 }
            val num2 = v2.getOrElse(i) { 0 }
            if (num1 != num2) return num1 - num2
        }
        return 0
    }

    private fun getDownloadUrl(release: GitHubRelease, abi: String): String {
        // Release assets are product-branded and distribution-neutral. Prefer the
        // exact ABI, then universal, and finally any APK as a safe last resort.
        val apkAssets = release.assets.filter { it.name.endsWith(".apk", true) }
        val asset = apkAssets.firstOrNull { it.name.contains(abi, true) }
            ?: apkAssets.firstOrNull { it.name.contains("universal", true) }
            ?: apkAssets.firstOrNull()

        return asset?.browserDownloadUrl
            ?: throw IllegalStateException("No compatible APK found")
    }
}
