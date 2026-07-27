package ir.dicode.ping.scanner

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import ir.dicode.ping.MainActivity
import ir.dicode.ping.R
import ir.dicode.ping.util.AppLog
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.distinctUntilChangedBy
import kotlinx.coroutines.launch

class ScannerService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var observeJob: Job? = null
    private var foregroundStarted = false

    override fun onCreate() {
        super.onCreate()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            getSystemService(NotificationManager::class.java).createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "Scanner", NotificationManager.IMPORTANCE_LOW)
            )
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val coordinator = ScannerCoordinator.get(applicationContext)
        if (intent?.action == ACTION_STOP) {
            if (!startForegroundSafely(ScannerState(stage = ScannerStage.STOPPED, result = "Stopping scanner"))) {
                ScannerCoordinator.get(applicationContext).requestStop()
                stopSelf(startId)
                return START_NOT_STICKY
            }
            observeJob?.cancel()
            observeJob = null
            coordinator.requestStop()
            scope.launch {
                runCatching { coordinator.join() }
                stopForeground(STOP_FOREGROUND_REMOVE)
                foregroundStarted = false
                stopSelf(startId)
            }
            return START_NOT_STICKY
        }

        if (!startForegroundSafely(ScannerState(stage = ScannerStage.CONNECTING, progress = 1))) {
            stopSelf(startId)
            return START_NOT_STICKY
        }
        runCatching { coordinator.start(intent?.getStringExtra(EXTRA_NAME).orEmpty()) }
            .onFailure { error ->
                AppLog.e("ScannerService", "Cannot start scanner", error)
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf(startId)
                return START_NOT_STICKY
            }

        observeJob?.cancel()
        observeJob = scope.launch {
            coordinator.state.distinctUntilChangedBy { state ->
                listOf(state.stage, state.progress, state.alive, state.stopRequested)
            }.collectLatest { state ->
                runCatching {
                    getSystemService(NotificationManager::class.java)
                        .notify(NOTIFICATION_ID, notification(state))
                }.onFailure { AppLog.w("ScannerService", "Notification update failed: ${it.message}") }

                if (!state.running && state.stage !in setOf(ScannerStage.IDLE, ScannerStage.CONNECTING)) {
                    stopForeground(STOP_FOREGROUND_REMOVE)
                    foregroundStarted = false
                    stopSelf(startId)
                }
            }
        }
        return START_NOT_STICKY
    }


    private fun startForegroundSafely(state: ScannerState): Boolean = runCatching {
        ensureForeground(state)
        true
    }.getOrElse { error ->
        AppLog.e("ScannerService", "Cannot enter foreground state", error)
        false
    }

    private fun ensureForeground(state: ScannerState) {
        if (foregroundStarted) return
        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
        } else {
            0
        }
        ServiceCompat.startForeground(
            this,
            NOTIFICATION_ID,
            notification(state),
            type,
        )
        foregroundStarted = true
    }

    private fun notification(state: ScannerState): Notification = NotificationCompat.Builder(this, CHANNEL_ID)
        .setSmallIcon(R.mipmap.ic_launcher)
        .setContentTitle("dicodePing Scanner")
        .setContentText("${state.stage.name.lowercase()} • ${state.progress}% • ${state.alive} healthy")
        .setProgress(100, state.progress, state.total == 0 && state.running)
        .setOngoing(state.running)
        .setOnlyAlertOnce(true)
        .setContentIntent(
            PendingIntent.getActivity(
                this,
                0,
                Intent(this, MainActivity::class.java),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )
        )
        .addAction(
            0,
            "Stop",
            PendingIntent.getService(
                this,
                1,
                Intent(this, ScannerService::class.java).setAction(ACTION_STOP),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            ),
        )
        .build()

    override fun onDestroy() {
        observeJob?.cancel()
        val coordinator = ScannerCoordinator.get(applicationContext)
        if (coordinator.state.value.running) coordinator.requestStop()
        scope.cancel()
        foregroundStarted = false
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        const val ACTION_STOP = "ir.dicode.ping.scanner.STOP"
        const val EXTRA_NAME = "scanner_name"
        private const val CHANNEL_ID = "dicodeping-scanner"
        private const val NOTIFICATION_ID = 4302
    }
}
