package com.adm.kiosk.ui.admin

import androidx.compose.foundation.background
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.adm.kiosk.ui.components.AdmHeader
import com.adm.kiosk.ui.theme.AdmYellow
import com.adm.kiosk.ui.theme.AdmBlack
import com.adm.kiosk.ui.theme.AdmBorder
import com.adm.kiosk.ui.theme.AdmDark
import com.adm.kiosk.ui.theme.AdmRed
import com.adm.kiosk.ui.theme.AdmSurfaceHi
import com.adm.kiosk.ui.theme.AdmText
import com.adm.kiosk.ui.theme.AdmTextDim
import kotlinx.coroutines.delay

@Composable
fun PinScreen(
    auth: AuthState,
    onSubmit: (String) -> Unit,
    onCancel: () -> Unit,
) {
    var entered by remember { mutableStateOf("") }

    // Clear the field shortly after an error so the user can retry.
    LaunchedEffect(auth.error) {
        if (auth.error != null) {
            delay(150)
            entered = ""
        }
    }

    fun press(d: Char) {
        if (entered.length < 4 && !auth.isLockedOut) {
            entered += d
            if (entered.length == 4) {
                onSubmit(entered)
            }
        }
    }

    Column(
        Modifier
            .fillMaxSize()
            .background(AdmDark),
    ) {
        AdmHeader(subtitle = "Administração — acesso restrito")

        Column(
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            Text(
                "Introduza o código de acesso",
                color = AdmText,
                fontSize = 20.sp,
                fontWeight = FontWeight.SemiBold,
            )
            Spacer(Modifier.height(20.dp))

            Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                repeat(4) { i ->
                    val filled = i < entered.length
                    Box(
                        Modifier
                            .size(22.dp)
                            .clip(CircleShape)
                            .background(if (filled) AdmBlack else AdmBorder),
                    )
                }
            }

            Spacer(Modifier.height(12.dp))
            Text(
                text = auth.error ?: " ",
                color = AdmRed,
                fontSize = 14.sp,
            )
            Spacer(Modifier.height(20.dp))

            val rows = listOf(
                listOf('1', '2', '3'),
                listOf('4', '5', '6'),
                listOf('7', '8', '9'),
            )
            rows.forEach { row ->
                Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                    row.forEach { d -> KeypadButton(d.toString()) { press(d) } }
                }
                Spacer(Modifier.height(16.dp))
            }
            Row(
                horizontalArrangement = Arrangement.spacedBy(16.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                OutlinedButton(
                    onClick = { if (entered.isNotEmpty()) entered = entered.dropLast(1) },
                    modifier = Modifier.size(88.dp),
                ) { Text("←", fontSize = 24.sp) }
                KeypadButton("0") { press('0') }
                OutlinedButton(
                    onClick = { entered = "" },
                    modifier = Modifier.size(88.dp),
                ) { Text("C", fontSize = 22.sp) }
            }

            Spacer(Modifier.height(24.dp))
            TextButton(onClick = onCancel) {
                Text("Voltar à apresentação", color = AdmTextDim)
            }
        }
    }
}

@Composable
private fun KeypadButton(label: String, onClick: () -> Unit) {
    Button(
        onClick = onClick,
        modifier = Modifier.size(88.dp),
        colors = ButtonDefaults.buttonColors(
            containerColor = AdmSurfaceHi,
            contentColor = AdmText,
        ),
    ) {
        Text(label, fontSize = 28.sp, fontWeight = FontWeight.Bold)
    }
}

