package com.adm.kiosk.util

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.os.Build
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.distinctUntilChanged

/**
 * Emits network availability changes so the kiosk can recover from connection loss.
 */
class NetworkMonitor(context: Context) {

    private val cm = context.applicationContext
        .getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager

    private var heldCallback: ConnectivityManager.NetworkCallback? = null

    /**
     * Existe uma ligação de rede ativa (Wi-Fi, Ethernet ou dados)? Não exige Internet
     * validada: uma rede local sem saída para a Internet continua a contar como ligada.
     */
    fun isConnected(): Boolean {
        val network = cm.activeNetwork ?: return false
        return isUsable(cm.getNetworkCapabilities(network))
    }

    private fun isUsable(caps: NetworkCapabilities?): Boolean {
        if (caps == null) return false
        return caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) ||
            caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) ||
            caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) ||
            caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
    }

    /**
     * Fica com a rede local mesmo quando o Android a marca como "sem Internet".
     * Sem isto, o WebView recusa páginas da LAN (ERR_INTERNET_DISCONNECTED).
     */
    fun holdLan() {
        val callback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) = bind(network)

            override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) {
                if (isUsable(caps)) bind(network)
            }
        }
        heldCallback = callback
        val request = NetworkRequest.Builder()
            .removeCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .build()
        val requested = runCatching { cm.requestNetwork(request, callback) }.isSuccess
        if (!requested) runCatching { cm.registerNetworkCallback(request, callback) }
        cm.activeNetwork?.let { bind(it) }
    }

    private fun bind(network: Network) {
        val caps = cm.getNetworkCapabilities(network) ?: return
        if (!isUsable(caps)) return
        runCatching {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                cm.bindProcessToNetwork(network)
            } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                @Suppress("DEPRECATION")
                ConnectivityManager.setProcessDefaultNetwork(network)
            }
        }
    }

    /** Existe Internet validada (acesso real à Internet). Usado para "Testar ligação". */
    fun isOnline(): Boolean {
        val network = cm.activeNetwork ?: return false
        val caps = cm.getNetworkCapabilities(network) ?: return false
        return caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) &&
            caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
    }

    /**
     * Emite o estado de ligação (link up/down). Deteta quedas de rede (ex.: um switch a
     * cair) e o restabelecimento, permitindo que o kiosk recarregue a página.
     */
    val online: Flow<Boolean> = callbackFlow {
        val callback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                trySend(isConnected())
            }

            override fun onLost(network: Network) {
                trySend(isConnected())
            }

            override fun onUnavailable() {
                trySend(false)
            }

            override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) {
                trySend(isUsable(caps))
                if (isUsable(caps)) bind(network)
            }
        }

        val request = NetworkRequest.Builder()
            .removeCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .build()

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            cm.registerDefaultNetworkCallback(callback)
        } else {
            cm.registerNetworkCallback(request, callback)
        }

        trySend(isConnected())
        awaitClose { runCatching { cm.unregisterNetworkCallback(callback) } }
    }.distinctUntilChanged()
}
