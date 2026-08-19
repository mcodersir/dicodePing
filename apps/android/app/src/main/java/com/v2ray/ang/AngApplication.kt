package com.v2ray.ang

import android.app.Application
import android.content.Context
import androidx.core.content.ContextCompat
import androidx.work.Configuration
import androidx.work.WorkManager
import com.v2ray.ang.AppConfig.ANG_PACKAGE
import com.v2ray.ang.handler.AppLocaleManager
import com.v2ray.ang.handler.MmkvManager
import com.v2ray.ang.handler.SettingsManager
import com.v2ray.ang.dto.entities.SubscriptionItem
import com.v2ray.ang.ui.compose.ThemeManager

class AngApplication : Application() {
    companion object {
        lateinit var application: AngApplication
    }

    /**
     * Attaches the base context to the application.
     * @param base The base context.
     */
    override fun attachBaseContext(base: Context?) {
        super.attachBaseContext(base?.let(ContextCompat::getContextForLanguage))
        application = this
    }

    private val workManagerConfiguration: Configuration = Configuration.Builder()
        .setDefaultProcessName("${ANG_PACKAGE}:bg")
        .build()

    /**
     * Initializes the application.
     */
    override fun onCreate() {
        super.onCreate()

        MmkvManager.initialize(this)

        // The product source is authoritative and is created once without
        // replacing any subscriptions the user adds later.
        if (MmkvManager.decodeSubscription(AppConfig.DICODE_PRIMARY_SUBSCRIPTION_ID) == null) {
            MmkvManager.encodeSubscription(
                AppConfig.DICODE_PRIMARY_SUBSCRIPTION_ID,
                SubscriptionItem(
                    remarks = "DicodePing",
                    url = AppConfig.DICODE_PRIMARY_SUBSCRIPTION_URL,
                    enabled = true,
                    autoUpdate = true,
                    updateInterval = 60,
                ),
            )
        }

        AppLocaleManager.initialize(this)

        // Initialize WorkManager with the custom configuration
        WorkManager.initialize(this, workManagerConfiguration)

        // Ensure critical preference defaults are present in MMKV early
        SettingsManager.initApp(this)

        // Preserve manual configurations while removing the old user-facing placeholder name.
        MmkvManager.decodeSubscription(AppConfig.DEFAULT_SUBSCRIPTION_ID)?.let { legacy ->
            if (legacy.remarks.equals("Default", ignoreCase = true)) {
                legacy.remarks = "Local configs"
                MmkvManager.encodeSubscription(AppConfig.DEFAULT_SUBSCRIPTION_ID, legacy)
            }
        }

        // Initialize theme state from MMKV
        ThemeManager.refresh()
    }
}
