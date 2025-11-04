package com.adm.kiosk.remote

import android.annotation.SuppressLint
import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.Build
import android.os.SystemClock
import android.provider.Settings
import com.adm.kiosk.BuildConfig
import com.adm.kiosk.kiosk.KioskManager
import com.adm.kiosk.util.DeviceType
import com.adm.kiosk.util.HomeLauncher
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.Inet4Address
import java.net.NetworkInterface
import java.util.UUID

/** Dados de rede do televisor (identificam qual TV é qual na rede). */
data class NetworkSnapshot(
    val ip: String = "",
    val prefix: Int = 0,
    val mask: String = "",
    val gateway: String = "",
    val dns: List<String> = emptyList(),
    val mac: String = "",
    val iface: String = "",
    val transport: String = "",
) {
    /** Endereço de broadcast da sub-rede (usado na descoberta do servidor). */
    val broadcast: String
        get() {
            if (ip.isBlank() || prefix !in 1..32) return ""
            val addr = ip.split('.').map { it.toInt() }
            val ipInt = (addr[0] shl 24) or (addr[1] shl 16) or (addr[2] shl 8) or addr[3]
            val maskInt = if (prefix == 32) -1 else (-1 shl (32 - prefix))
            val b = ipInt or maskInt.inv()
            return "${b ushr 24 and 255}.${b ushr 16 and 255}.${b ushr 8 and 255}.${b and 255}"
        }

    fun toJson(): JSONObject = JSONObject()
        .put("ip", ip)
        .put("prefix", prefix)
        .put("mask", mask)
        .put("gateway", gateway)
        .put("dns", JSONArray(dns))
        .put("mac", mac)
        .put("iface", iface)
        .put("transport", transport)
}

object DeviceInfo {

    private const val PREFS = "remote_agent"
    private const val KEY_UUID = "fallback_id"

    /** Identificador estável do televisor (ANDROID_ID; UUID gerado como alternativa). */
    @SuppressLint("HardwareIds")
    fun deviceId(context: Context): String {
        val androidId = Settings.Secure.getString(context.contentResolver, Settings.Secure.ANDROID_ID)
        if (!androidId.isNullOrBlank() && androidId != "9774d56d682e549c") return androidId
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        return prefs.getString(KEY_UUID, null) ?: UUID.randomUUID().toString().replace("-", "").also {
            prefs.edit().putString(KEY_UUID, it).apply()
        }
    }

    fun network(context: Context): NetworkSnapshot {
        val cm = context.applicationContext
            .getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val net = cm.activeNetwork ?: return NetworkSnapshot()
        val lp = cm.getLinkProperties(net) ?: return NetworkSnapshot()
        val caps = cm.getNetworkCapabilities(net)

        val v4 = lp.linkAddresses.firstOrNull { it.address is Inet4Address }
        val prefix = v4?.prefixLength ?: 0
        val gateway = lp.routes
            .firstOrNull { it.isDefaultRoute && it.gateway is Inet4Address }
            ?.gateway?.hostAddress.orEmpty()
        val transport = when {
            caps == null -> ""
            caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "Ethernet"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "Wi-Fi"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "Móvel"
            else -> "Outra"
        }
        val iface = lp.interfaceName.orEmpty()
        return NetworkSnapshot(
            ip = v4?.address?.hostAddress.orEmpty(),
            prefix = prefix,
            mask = prefixToMask(prefix),
            gateway = gateway,
            dns = lp.dnsServers.mapNotNull { it.hostAddress },
            mac = macAddress(iface),
            iface = iface,
            transport = transport,
        )
    }

    private fun prefixToMask(prefix: Int): String {
        if (prefix !in 1..32) return ""
        val m = if (prefix == 32) -1 else (-1 shl (32 - prefix))
        return "${m ushr 24 and 255}.${m ushr 16 and 255}.${m ushr 8 and 255}.${m and 255}"
    }

    /** Recent Android versions may hide the MAC address; in that case it stays empty. */
    private fun macAddress(iface: String): String {
        if (iface.isBlank()) return ""
        runCatching {
            val bytes = NetworkInterface.getByName(iface)?.hardwareAddress
            if (bytes != null && bytes.isNotEmpty()) {
                val mac = bytes.joinToString(":") { "%02X".format(it) }
                if (mac != "02:00:00:00:00:00") return mac
            }
        }
        runCatching {
            val mac = File("/sys/class/net/$iface/address").readText().trim().uppercase()
            if (mac.isNotBlank() && mac != "02:00:00:00:00:00") return mac
        }
        return ""
    }

    fun device(context: Context): JSONObject {
        val dm = context.resources.displayMetrics
        val realSize = runCatching {
            val wm = context.getSystemService(Context.WINDOW_SERVICE) as android.view.WindowManager
            val p = android.graphics.Point()
            @Suppress("DEPRECATION")
            wm.defaultDisplay.getRealSize(p)
            "${p.x}x${p.y}"
        }.getOrDefault("${dm.widthPixels}x${dm.heightPixels}")
        val km = KioskManager(context)
        return JSONObject()
            .put("manufacturer", Build.MANUFACTURER)
            .put("model", Build.MODEL)
            .put("android", Build.VERSION.RELEASE)
            .put("sdk", Build.VERSION.SDK_INT)
            .put("resolution", realSize)
            .put("uptimeSec", SystemClock.elapsedRealtime() / 1000)
            .put("isTv", DeviceType.isTelevision(context))
            .put("deviceOwner", km.isDeviceOwner())
            .put("isLauncher", HomeLauncher.isDefaultHome(context))
            .put("appVersion", BuildConfig.VERSION_NAME)
            .put("appVersionCode", BuildConfig.VERSION_CODE)
    }
}
