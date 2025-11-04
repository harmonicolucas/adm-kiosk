package com.adm.kiosk.ui.admin

import android.app.Activity
import androidx.compose.foundation.background
import androidx.compose.runtime.DisposableEffect
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import com.adm.kiosk.util.HomeLauncher
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.adm.kiosk.ui.components.AdmHeader
import com.adm.kiosk.ui.theme.AdmGreen
import com.adm.kiosk.ui.theme.AdmDark
import com.adm.kiosk.ui.theme.AdmInk
import com.adm.kiosk.ui.theme.AdmRed
import com.adm.kiosk.ui.theme.AdmWhite

@Composable
fun SettingsScreen(
    vm: AdminViewModel,
    onBack: () -> Unit,
) {
    val context = LocalContext.current
    val settings by vm.settingsFlow.collectAsState()

    var showPinDialog by remember { mutableStateOf(false) }
    var showExitDialog by remember { mutableStateOf(false) }
    var exitError by remember { mutableStateOf<String?>(null) }
    var statusMessage by remember { mutableStateOf<String?>(null) }
    var showServerDialog by remember { mutableStateOf(false) }
    val remote by vm.remoteStatus.collectAsState()

    // Re-read the launcher status whenever the screen returns from Android settings.
    var isHome by remember { mutableStateOf(HomeLauncher.isDefaultHome(context)) }
    var canAutoStart by remember { mutableStateOf(HomeLauncher.canStartFromBackground(context)) }
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                isHome = HomeLauncher.isDefaultHome(context)
                canAutoStart = HomeLauncher.canStartFromBackground(context)
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    Column(
        Modifier
            .fillMaxSize()
            .background(AdmDark),
    ) {
        AdmHeader(
            subtitle = "Definições",
            trailing = {
                OutlinedButton(onClick = onBack) { Text("Voltar") }
            },
        )

        Column(
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(20.dp),
        ) {
            statusMessage?.let {
                Text(it, color = AdmInk, modifier = Modifier.padding(bottom = 8.dp))
            }

            SectionTitle("Definições de apresentação")
            StepperRow(
                label = "Intervalo de atualização",
                value = formatRefresh(settings.refreshIntervalSeconds),
                onMinus = { vm.setRefreshInterval(prevRefresh(settings.refreshIntervalSeconds)) },
                onPlus = { vm.setRefreshInterval(nextRefresh(settings.refreshIntervalSeconds)) },
            )
            StepperRow(
                label = "Zoom (sem alterar a disposição do texto)",
                value = "${settings.zoomPercent}%",
                onMinus = { vm.setZoom(settings.zoomPercent - 10) },
                onPlus = { vm.setZoom(settings.zoomPercent + 10) },
            )
            StepperRow(
                label = "Atraso de nova tentativa (falha de rede)",
                value = "${settings.retryDelaySeconds}s",
                onMinus = { vm.setRetryDelay(settings.retryDelaySeconds - 5) },
                onPlus = { vm.setRetryDelay(settings.retryDelaySeconds + 5) },
            )
            ToggleRow(
                label = "Recarregar automaticamente em caso de falha",
                checked = settings.reloadOnError,
                onChange = { vm.setReloadOnError(it) },
            )
            ToggleRow(
                label = "Modo Kiosk (Lock Task) ativo",
                checked = settings.kioskModeEnabled,
                onChange = { vm.setKioskEnabled(it) },
            )
            ToggleRow(
                label = "Rodar automaticamente os voos cortados",
                checked = settings.autoScrollEnabled,
                onChange = { vm.setAutoScroll(it) },
            )
            if (settings.autoScrollEnabled) {
                StepperRow(
                    label = "Tempo de cada ecrã de voos",
                    value = "${settings.autoScrollSeconds}s",
                    onMinus = { vm.setAutoScrollSeconds(settings.autoScrollSeconds - 5) },
                    onPlus = { vm.setAutoScrollSeconds(settings.autoScrollSeconds + 5) },
                )
            }

            Spacer(Modifier.height(12.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                OutlinedButton(onClick = {
                    vm.testConnection { ok ->
                        statusMessage = if (ok) "Ligação OK à Internet" else "Sem ligação à Internet"
                    }
                }) { Text("Testar ligação") }
                OutlinedButton(onClick = onBack) { Text("Voltar à apresentação") }
            }

            Spacer(Modifier.height(28.dp))
            SectionTitle("Gestão remota (administrador web)")
            Text(
                remote.message + if (remote.server.isNotBlank()) " - ${remote.server}" else "",
                color = if (remote.connected) AdmGreen else AdmRed,
                fontSize = 13.sp,
            )
            Text(
                "ID do televisor: ${vm.deviceId().takeLast(8).uppercase()}" +
                    if (settings.deviceName.isNotBlank()) "   Nome: ${settings.deviceName}" else "",
                color = AdmInk,
                fontSize = 13.sp,
            )
            if (settings.remoteUrl.isNotBlank()) {
                Text(
                    "Página definida pelo servidor: ${settings.remoteUrl}",
                    color = AdmInk,
                    fontSize = 13.sp,
                )
            }
            ToggleRow(
                label = "Permitir configuração remota",
                checked = settings.remoteEnabled,
                onChange = { vm.setRemoteEnabled(it) },
            )
            Spacer(Modifier.height(6.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                OutlinedButton(onClick = { showServerDialog = true }) {
                    Text(
                        if (settings.serverUrl.isBlank()) "Servidor: automático"
                        else "Servidor: ${settings.serverUrl}",
                    )
                }
                OutlinedButton(onClick = {
                    vm.rediscoverServer()
                    statusMessage = "A procurar o servidor na rede…"
                }) { Text("Procurar servidor agora") }
            }

            Spacer(Modifier.height(28.dp))
            SectionTitle("Launcher (ecrã inicial do Android)")
            Text(
                if (isHome) "Esta aplicação é o launcher: abre sozinha sempre que o Android inicia."
                else "Esta aplicação ainda não é o launcher predefinido.",
                color = if (isHome) AdmGreen else AdmRed,
                fontSize = 13.sp,
            )
            if (!canAutoStart) {
                Text(
                    "Arranque automático sem launcher bloqueado: falta a permissão \"Sobrepor a outras apps\".",
                    color = AdmRed,
                    fontSize = 13.sp,
                )
            }
            Spacer(Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                if (!isHome) {
                    Button(onClick = {
                        val act = context as? Activity ?: return@Button
                        if (!HomeLauncher.requestDefaultHome(act)) {
                            statusMessage = "Esta TV não permite escolher o launcher no ecrã. Use ADB: " +
                                "adb shell cmd package set-home-activity com.adm.kiosk/.ui.kiosk.KioskActivity"
                        }
                    }) { Text("Definir como launcher") }
                }
                if (!canAutoStart) {
                    OutlinedButton(onClick = {
                        val act = context as? Activity ?: return@OutlinedButton
                        if (!HomeLauncher.openOverlayPermission(act)) {
                            statusMessage = "Esta TV não tem o ecrã de permissão de sobreposição."
                        }
                    }) { Text("Permitir arranque automático") }
                }
            }

            Spacer(Modifier.height(28.dp))
            SectionTitle("Segurança")
            Text(
                if (vm.isDeviceOwner()) "Device Owner ativo — Kiosk real disponível."
                else "Device Owner inativo — a usar modo de fixação (screen pinning).",
                color = if (vm.isDeviceOwner()) AdmGreen else AdmRed,
                fontSize = 13.sp,
            )
            Spacer(Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                OutlinedButton(onClick = { showPinDialog = true }) {
                    Text("Alterar código de acesso")
                }
                Button(
                    onClick = { exitError = null; showExitDialog = true },
                    colors = ButtonDefaults.buttonColors(
                        containerColor = AdmRed, contentColor = AdmWhite,
                    ),
                ) { Text("Sair do modo Kiosk") }
            }

            Spacer(Modifier.height(30.dp))
        }
    }

    if (showPinDialog) {
        ChangePinDialog(
            onDismiss = { showPinDialog = false },
            onConfirm = { current, newPin ->
                vm.changePin(current, newPin) { ok, err ->
                    statusMessage = if (ok) "Código alterado com sucesso" else err
                    if (ok) showPinDialog = false
                }
            },
        )
    }

    if (showServerDialog) {
        ServerAddressDialog(
            initial = settings.serverUrl,
            onDismiss = { showServerDialog = false },
            onSave = {
                vm.setServerUrl(it)
                showServerDialog = false
                statusMessage = if (it.isBlank()) "Servidor: descoberta automática" else "Servidor definido: $it"
            },
        )
    }

    if (showExitDialog) {
        PinPromptDialog(
            title = "Sair do modo Kiosk",
            message = "Introduza o código de acesso para sair. O ecrã voltará ao menu do Android.",
            confirmLabel = "Sair",
            error = exitError,
            onDismiss = { showExitDialog = false },
            onConfirm = { pin ->
                vm.checkPin(pin) { ok ->
                    if (ok) {
                        showExitDialog = false
                        (context as? AdminActivity)?.let { act ->
                            vm.exitKiosk(act, disableKiosk = true) { act.finish() }
                        }
                    } else {
                        exitError = "Código incorreto"
                    }
                }
            },
        )
    }
}
