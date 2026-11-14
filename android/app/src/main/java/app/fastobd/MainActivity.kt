package app.fastobd

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothSocket
import android.content.ContentValues
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.MediaStore
import android.view.WindowManager
import android.webkit.GeolocationPermissions
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebView
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.UUID

/**
 * Thin shell around the logger page (assets/index.html).
 * The page talks to the dongle through the AndroidBT object below: classic Bluetooth SPP (RFCOMM).
 * The shell only moves bytes. All OBD logic, and the rule that only read requests are sent, lives in the page.
 */
class MainActivity : Activity() {
    private lateinit var web: WebView
    private var socket: BluetoothSocket? = null
    private var selfClose = false
    private val writeLock = Any()
    private val spp: UUID = UUID.fromString("00001101-0000-1000-8000-00805F9B34FB")

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        web = WebView(this)
        setContentView(web)
        web.setRendererPriorityPolicy(WebView.RENDERER_PRIORITY_IMPORTANT, false)
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.settings.mediaPlaybackRequiresUserGesture = false
        web.webChromeClient = object : WebChromeClient() {
            override fun onGeolocationPermissionsShowPrompt(origin: String, callback: GeolocationPermissions.Callback) {
                callback.invoke(origin, checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED, false)
            }
        }
        web.addJavascriptInterface(Bridge(), "AndroidBT")
        askPermissions()
        val html = assets.open("index.html").bufferedReader().use { it.readText() }
        web.loadDataWithBaseURL("https://fastobd.app/", html, "text/html", "utf-8", null)
    }

    private fun askPermissions() {
        val need = ArrayList<String>()
        if (Build.VERSION.SDK_INT >= 31) {
            if (checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED) need.add(Manifest.permission.BLUETOOTH_CONNECT)
            if (checkSelfPermission(Manifest.permission.BLUETOOTH_SCAN) != PackageManager.PERMISSION_GRANTED) need.add(Manifest.permission.BLUETOOTH_SCAN)
        }
        if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            need.add(Manifest.permission.ACCESS_FINE_LOCATION)
        }
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            need.add(Manifest.permission.POST_NOTIFICATIONS)
        }
        if (need.isNotEmpty()) requestPermissions(need.toTypedArray(), 1)
        startKeepAlive()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        startKeepAlive()
    }

    // A foreground service keeps the app (and its Bluetooth link) alive with the screen off or another app on top.
    private fun startKeepAlive() {
        try {
            if (Build.VERSION.SDK_INT < 31 || checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) == PackageManager.PERMISSION_GRANTED) {
                startForegroundService(Intent(this, KeepAliveService::class.java))
            }
        } catch (e: Exception) { }
    }

    private fun js(code: String) {
        runOnUiThread { web.evaluateJavascript(code, null) }
    }

    private fun adapter(): BluetoothAdapter? {
        val m = getSystemService(BLUETOOTH_SERVICE) as BluetoothManager
        return m.adapter
    }

    override fun onDestroy() {
        selfClose = true
        stopService(Intent(this, KeepAliveService::class.java))
        try { socket?.close() } catch (e: IOException) { }
        super.onDestroy()
    }

    inner class Bridge {
        @JavascriptInterface
        fun hasPerm(): Boolean {
            return Build.VERSION.SDK_INT < 31 ||
                (checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) == PackageManager.PERMISSION_GRANTED &&
                 checkSelfPermission(Manifest.permission.BLUETOOTH_SCAN) == PackageManager.PERMISSION_GRANTED)
        }

        @JavascriptInterface
        fun keepAwake(on: Boolean) {
            runOnUiThread {
                if (on) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            }
        }

        @JavascriptInterface
        fun askPerm() {
            runOnUiThread { askPermissions() }
        }

        @SuppressLint("MissingPermission")
        @JavascriptInterface
        fun listPaired(): String {
            val arr = JSONArray()
            try {
                val a = adapter() ?: return arr.toString()
                for (d in a.bondedDevices) {
                    val o = JSONObject()
                    o.put("name", d.name ?: "")
                    o.put("addr", d.address)
                    arr.put(o)
                }
            } catch (e: Exception) { }
            return arr.toString()
        }

        @SuppressLint("MissingPermission")
        @JavascriptInterface
        fun connect(addr: String) {
            Thread {
                try {
                    close()
                    val a = adapter() ?: throw IOException("Bluetooth is off")
                    try { a.cancelDiscovery() } catch (e: SecurityException) { }
                    val s = a.getRemoteDevice(addr).createRfcommSocketToServiceRecord(spp)
                    s.connect()
                    selfClose = false
                    socket = s
                    js("window.__btConnected(true,'')")
                    readLoop(s)
                } catch (e: Exception) {
                    js("window.__btConnected(false," + JSONObject.quote(e.message ?: "connection failed") + ")")
                }
            }.start()
        }

        @JavascriptInterface
        fun write(s: String) {
            synchronized(writeLock) {
                try {
                    val out = socket?.outputStream
                    out?.write(s.toByteArray(Charsets.ISO_8859_1))
                    out?.flush()
                } catch (e: IOException) { }
            }
        }

        @JavascriptInterface
        fun close() {
            selfClose = true
            try { socket?.close() } catch (e: IOException) { }
            socket = null
        }

        @JavascriptInterface
        fun save(name: String, text: String, mime: String): String {
            val v = ContentValues()
            v.put(MediaStore.MediaColumns.DISPLAY_NAME, name)
            v.put(MediaStore.MediaColumns.MIME_TYPE, mime)
            v.put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
            val uri = contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, v)
                ?: throw IOException("could not create file")
            contentResolver.openOutputStream(uri).use { it!!.write(text.toByteArray(Charsets.UTF_8)) }
            return "Downloads/$name"
        }
    }

    private fun readLoop(s: BluetoothSocket) {
        val buf = ByteArray(1024)
        var reason = "adapter closed the link"
        try {
            val ins = s.inputStream
            while (true) {
                val n = ins.read(buf)
                if (n < 0) break
                js("window.__btRx(" + JSONObject.quote(String(buf, 0, n, Charsets.ISO_8859_1)) + ")")
            }
        } catch (e: IOException) { reason = e.message ?: "read error" }
        if (!selfClose && socket === s) {
            socket = null
            js("window.__btClosed(" + JSONObject.quote(reason) + ")")
        }
    }
}
