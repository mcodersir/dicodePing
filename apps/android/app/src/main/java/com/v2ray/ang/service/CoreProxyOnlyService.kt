package com.v2ray.ang.service

import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.IBinder
import com.v2ray.ang.AppConfig
import com.v2ray.ang.contracts.ServiceControl
import com.v2ray.ang.core.CoreServiceManager
import com.v2ray.ang.handler.AppLocaleManager
import com.v2ray.ang.handler.NotificationManager
import com.v2ray.ang.util.LogUtil
import java.lang.ref.SoftReference

class CoreProxyOnlyService : Service(), ServiceControl {
    private val ending = java.util.concurrent.atomic.AtomicBoolean(false)
    private val starting = java.util.concurrent.atomic.AtomicBoolean(false)
    /**
     * Initializes the service.
     */
    override fun onCreate() {
        super.onCreate()
        LogUtil.i(AppConfig.TAG, "StartCore-Proxy: Service created")
        CoreServiceManager.serviceControl = SoftReference(this)
    }

    /**
     * Handles the start command for the service.
     * @param intent The intent.
     * @param flags The flags.
     * @param startId The start ID.
     * @return The start mode.
     */
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        NotificationManager.ensureForeground()
        if (!com.v2ray.ang.core.LauncherManager.isCurrentStartRequest(intent)) {
            if (CoreServiceManager.isServiceRunning()) return START_STICKY
            stopSelf(startId)
            return START_NOT_STICKY
        }
        LogUtil.i(AppConfig.TAG, "StartCore-Proxy: Service command received")

        // A reload has Xray stopped for a moment; a start on top of it would run beside the reload.
        if (CoreServiceManager.isServiceRunning()) {
            LogUtil.i(AppConfig.TAG, "StartCore-Proxy: Core is already running")
            return START_STICKY
        }

        if (!starting.compareAndSet(false, true)) return START_NOT_STICKY
        CoreLifecycleWorker.executor.execute {
            try {
                if (ending.get() || !com.v2ray.ang.core.LauncherManager.isCurrentStartRequest(intent)) return@execute
                NotificationManager.ensureForeground()
                if (!CoreServiceManager.startCoreLoop(null, this) || ending.get()) stopSelf()
            } catch (error: Exception) {
                LogUtil.e(AppConfig.TAG, "Core service startup failed", error)
                stopSelf()
            } finally { starting.set(false) }
        }
        return START_NOT_STICKY
    }

    /**
     * Destroys the service.
     */
    override fun onDestroy() {
        super.onDestroy()
        ending.set(true)
        CoreServiceManager.cancelFoxStartup(this)
        CoreLifecycleWorker.executor.execute {
            CoreServiceManager.stopCoreLoop(this)
            CoreServiceManager.serviceDestroyed(this)
        }
    }

    /**
     * Gets the service instance.
     * @return The service instance.
     */
    override fun getService(): Service {
        return this
    }

    /**
     * Starts the service.
     */
    override fun startService() {
        // do nothing
    }

    /**
     * Stops the service.
     */
    override fun stopService() {
        ending.set(true)
        CoreServiceManager.cancelFoxStartup(this)
        stopSelf()
    }

    /**
     * Protects the VPN socket.
     * @param socket The socket to protect.
     * @return True if the socket is protected, false otherwise.
     */
    override fun vpnProtect(socket: Int): Boolean {
        return true
    }

    /**
     * Binds the service.
     * @param intent The intent.
     * @return The binder.
     */
    override fun onBind(intent: Intent?): IBinder? {
        return null
    }

    /**
     * Attaches the base context to the service.
     * @param newBase The new base context.
     */
    override fun attachBaseContext(newBase: Context?) {
        val context = newBase?.let(AppLocaleManager::localizedContext)
        super.attachBaseContext(context)
    }
}
