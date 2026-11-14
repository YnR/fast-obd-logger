package app.fastobd

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.IBinder
import android.os.PowerManager

/** Keeps the process alive (and the CPU awake) so logging continues with the screen off or the app in the background. */
class KeepAliveService : Service() {
    private var wake: PowerManager.WakeLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel("obd", "Logger running", NotificationManager.IMPORTANCE_LOW))
        val pi = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val n = Notification.Builder(this, "obd")
            .setContentTitle("Fast OBD Logger")
            .setContentText("Connected to the car, logging in the background")
            .setSmallIcon(android.R.drawable.stat_sys_data_bluetooth)
            .setContentIntent(pi)
            .setOngoing(true)
            .build()
        startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)
        if (wake == null) {
            val pm = getSystemService(PowerManager::class.java)
            wake = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "fastobd:log")
            wake?.acquire()
        }
        return START_STICKY
    }

    override fun onDestroy() {
        try { wake?.release() } catch (e: Exception) { }
        wake = null
        super.onDestroy()
    }
}
