package ir.dicode.ping.scanner

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import ir.dicode.ping.MainActivity
import ir.dicode.ping.R
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch

class ScannerService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var observeJob: Job? = null

    override fun onCreate() {
        super.onCreate()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            getSystemService(NotificationManager::class.java).createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "Scanner", NotificationManager.IMPORTANCE_LOW)
            )
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val coordinator = ScannerCoordinator.get(this)
        if (intent?.action == ACTION_STOP) {
            coordinator.requestStop()
            return START_NOT_STICKY
        }
        startForeground(NOTIFICATION_ID, notification(ScannerState(stage = ScannerStage.CONNECTING)))
        coordinator.start(intent?.getStringExtra(EXTRA_NAME).orEmpty())
        observeJob?.cancel()
        observeJob = scope.launch {
            coordinator.state.collectLatest { state ->
                getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID, notification(state))
                if (!state.running && state.stage !in setOf(ScannerStage.IDLE, ScannerStage.CONNECTING)) stopSelf()
            }
        }
        return START_NOT_STICKY
    }

    private fun notification(state: ScannerState) = NotificationCompat.Builder(this, CHANNEL_ID)
        .setSmallIcon(R.mipmap.ic_launcher)
        .setContentTitle("dicodePing Scanner")
        .setContentText("${state.stage.name.lowercase()} • ${state.progress}% • ${state.alive} healthy")
        .setProgress(100, state.progress, state.total == 0)
        .setOngoing(state.running)
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
        scope.cancel()
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
