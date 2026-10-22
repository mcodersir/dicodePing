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
import com.v2ray.ang.root.RootProxyManager
import com.v2ray.ang.util.LogUtil
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import java.lang.ref.SoftReference

/**
 * Foreground service for the root (system-wide) run modes. Unlike [CoreVpnService] it
 * does not use Android VpnService — traffic is routed by iptables instead
 * (see [RootProxyManager]).
 *
 * The in-process core is started first (so its listener is up and the foreground
 * notification is posted promptly), then the root routing rules are installed off the
 * main thread. On teardown the rules are removed before the core stops.
 */
class CoreRootService : Service(), ServiceControl {

    private val ending = java.util.concurrent.atomic.AtomicBoolean(false)
    private val starting = java.util.concurrent.atomic.AtomicBoolean(false)

    override fun onCreate() {
        super.onCreate()
        LogUtil.i(AppConfig.TAG, "StartCore-Root: Service created")
        CoreServiceManager.serviceControl = SoftReference(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        NotificationManager.ensureForeground()
        if (!com.v2ray.ang.core.LauncherManager.isCurrentStartRequest(intent)) {
            if (CoreServiceManager.isServiceRunning()) return START_STICKY
            stopSelf(startId)
            return START_NOT_STICKY
        }
        LogUtil.i(AppConfig.TAG, "StartCore-Root: command received")

        // A reload has Xray stopped for a moment; a start on top of it would run beside the reload and
        // take the root rules and the tunnel down to install them again, with the traffic unrouted meanwhile.
        if (CoreServiceManager.isServiceRunning()) {
            LogUtil.i(AppConfig.TAG, "StartCore-Root: Core is already running")
            return START_STICKY
        }

        if (!starting.compareAndSet(false, true)) return START_NOT_STICKY
        CoreLifecycleWorker.executor.execute {
            try {
                if (ending.get() || !com.v2ray.ang.core.LauncherManager.isCurrentStartRequest(intent)) return@execute
                NotificationManager.ensureForeground()
                if (!CoreServiceManager.startCoreLoop(null, this) || ending.get()) { stopSelf(); return@execute }
                if (!RootProxyManager.start(this@CoreRootService) || ending.get()) stopSelf()
            } catch (error: Exception) {
                LogUtil.e(AppConfig.TAG, "Core service startup failed", error)
                stopSelf()
            } finally { starting.set(false) }
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        super.onDestroy()
        ending.set(true)
        CoreServiceManager.cancelFoxStartup(this)
        CoreLifecycleWorker.executor.execute {
            // Teardown is ordered before a later service start, without blocking Android's main thread.
            RootProxyManager.stop(this)
            CoreServiceManager.stopCoreLoop(this)
            CoreServiceManager.serviceDestroyed(this)
        }
    }

    override fun getService(): Service = this

    override fun startService() {
        // do nothing
    }

    override fun stopService() {
        ending.set(true)
        CoreServiceManager.cancelFoxStartup(this)
        stopSelf()
    }

    override fun vpnProtect(socket: Int): Boolean = true

    override fun onBind(intent: Intent?): IBinder? = null

    override fun attachBaseContext(newBase: Context?) {
        val context = newBase?.let(AppLocaleManager::localizedContext)
        super.attachBaseContext(context)
    }
}
