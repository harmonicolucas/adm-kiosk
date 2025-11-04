package com.adm.kiosk.ui.admin

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringArrayResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.unit.dp
import com.adm.kiosk.R
import com.adm.kiosk.data.db.WebLink
import com.adm.kiosk.ui.theme.AdmRed

@Composable
fun LinkEditDialog(
    initial: WebLink?,
    onDismiss: () -> Unit,
    onSave: (WebLink) -> Unit,
) {
    val categories = stringArrayResource(R.array.page_types).toList()
    var name by remember { mutableStateOf(initial?.name ?: "") }
    var url by remember { mutableStateOf(initial?.url ?: "https://") }
    var category by remember { mutableStateOf(initial?.category ?: categories.firstOrNull() ?: "") }
    var expanded by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (initial == null) "Adicionar link" else "Editar link") },
        text = {
            Column {
                OutlinedTextField(
                    value = name,
                    onValueChange = { name = it },
                    label = { Text("Nome do link") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(10.dp))
                OutlinedTextField(
                    value = url,
                    onValueChange = { url = it },
                    label = { Text("Endereço (http, https ou IP)") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(10.dp))
                OutlinedButton(onClick = { expanded = true }, modifier = Modifier.fillMaxWidth()) {
                    Text("Tipo de página: $category")
                }
                DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
                    categories.forEach { c ->
                        DropdownMenuItem(text = { Text(c) }, onClick = {
                            category = c
                            expanded = false
                        })
                    }
                }
                error?.let {
                    Spacer(Modifier.height(8.dp))
                    Text(it, color = AdmRed)
                }
            }
        },
        confirmButton = {
            TextButton(onClick = {
                val normalized = normalizeUrl(url)
                when {
                    name.isBlank() -> error = "Indique um nome"
                    normalized == null -> error = "Endereço inválido (use http://, https:// ou um IP/host)"
                    else -> onSave(
                        (initial ?: WebLink(name = "", url = "")).copy(
                            name = name.trim(),
                            url = normalized,
                            category = category,
                        ),
                    )
                }
            }) { Text("Guardar") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancelar") }
        },
    )
}

/**
 * Aceita http://, https:// ou um IP/host (com ou sem porta/caminho). Se não tiver
 * esquema, assume http://. Devolve o URL normalizado ou null se for inválido.
 */
private fun normalizeUrl(raw: String): String? {
    val input = raw.trim()
    if (input.isEmpty()) return null

    val withScheme = if (input.startsWith("http://") || input.startsWith("https://")) {
        input
    } else {
        "http://$input"
    }

    // A parte a seguir ao esquema (host[:porta][/caminho]) tem de existir.
    val afterScheme = withScheme.substringAfter("://", "")
    val host = afterScheme.substringBefore('/').substringBefore(':')
    if (host.isBlank()) return null
    // Host válido: IP (dígitos e pontos) ou nome de domínio simples.
    val hostOk = host.matches(Regex("^[A-Za-z0-9.-]+$"))
    return if (hostOk) withScheme else null
}

@Composable
fun ChangePinDialog(
    onDismiss: () -> Unit,
    onConfirm: (current: String, newPin: String) -> Unit,
) {
    var current by remember { mutableStateOf("") }
    var newPin by remember { mutableStateOf("") }
    var confirm by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Alterar código de acesso") },
        text = {
            Column {
                PinField("Código atual", current) { if (it.length <= 4) current = it }
                Spacer(Modifier.height(10.dp))
                PinField("Novo código (4 dígitos)", newPin) { if (it.length <= 4) newPin = it }
                Spacer(Modifier.height(10.dp))
                PinField("Confirmar novo código", confirm) { if (it.length <= 4) confirm = it }
                error?.let {
                    Spacer(Modifier.height(8.dp))
                    Text(it, color = AdmRed)
                }
            }
        },
        confirmButton = {
            TextButton(onClick = {
                if (newPin != confirm) {
                    error = "A confirmação não coincide"
                } else {
                    onConfirm(current, newPin)
                }
            }) { Text("Confirmar") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancelar") } },
    )
}

@Composable
private fun PinField(label: String, value: String, onChange: (String) -> Unit) {
    OutlinedTextField(
        value = value,
        onValueChange = { input -> onChange(input.filter { it.isDigit() }) },
        label = { Text(label) },
        singleLine = true,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
        modifier = Modifier.fillMaxWidth(),
    )
}

@Composable
fun PinPromptDialog(
    title: String,
    message: String,
    confirmLabel: String,
    error: String?,
    onDismiss: () -> Unit,
    onConfirm: (pin: String) -> Unit,
) {
    var pin by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            Column {
                Text(message)
                Spacer(Modifier.height(10.dp))
                PinField("Código (4 dígitos)", pin) { if (it.length <= 4) pin = it }
                error?.let {
                    Spacer(Modifier.height(8.dp))
                    Text(it, color = AdmRed)
                }
            }
        },
        confirmButton = { TextButton(onClick = { onConfirm(pin) }) { Text(confirmLabel) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancelar") } },
    )
}

/** Endereço do servidor central; vazio = descoberta automática na rede. */
@Composable
fun ServerAddressDialog(
    initial: String,
    onDismiss: () -> Unit,
    onSave: (String) -> Unit,
) {
    var value by remember { mutableStateOf(initial) }
    var error by remember { mutableStateOf<String?>(null) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Servidor de administração") },
        text = {
            Column {
                Text("Deixe vazio para encontrar o servidor automaticamente na rede.")
                Spacer(Modifier.height(10.dp))
                OutlinedTextField(
                    value = value,
                    onValueChange = { value = it },
                    label = { Text("Endereço (ex.: 10.0.0.5:8080)") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                    modifier = Modifier.fillMaxWidth(),
                )
                error?.let {
                    Spacer(Modifier.height(8.dp))
                    Text(it, color = AdmRed)
                }
            }
        },
        confirmButton = {
            TextButton(onClick = {
                if (value.isBlank()) {
                    onSave("")
                } else {
                    val normalized = normalizeUrl(value)
                    if (normalized == null) error = "Endereço inválido" else onSave(normalized)
                }
            }) { Text("Guardar") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancelar") } },
    )
}

@Composable
fun ConfirmDialog(
    title: String,
    message: String,
    confirmLabel: String,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = { Text(message) },
        confirmButton = { TextButton(onClick = onConfirm) { Text(confirmLabel) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancelar") } },
    )
}


