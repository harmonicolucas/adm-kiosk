package com.adm.kiosk.ui.admin

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.outlined.StarBorder
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringArrayResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.adm.kiosk.R
import com.adm.kiosk.data.db.WebLink
import com.adm.kiosk.ui.components.AdmHeader
import com.adm.kiosk.ui.theme.AdmBlack
import com.adm.kiosk.ui.theme.AdmGreen
import com.adm.kiosk.ui.theme.AdmDark
import com.adm.kiosk.ui.theme.AdmInk
import com.adm.kiosk.ui.theme.AdmRed
import com.adm.kiosk.ui.theme.AdmSurface
import com.adm.kiosk.ui.theme.AdmText
import com.adm.kiosk.ui.theme.AdmTextDim
import com.adm.kiosk.ui.theme.AdmWhite
import com.adm.kiosk.ui.theme.AdmYellow

private const val ALL_CATEGORIES = "Todas"

@Composable
fun AdminScreen(
    vm: AdminViewModel,
    onOpenSettings: () -> Unit,
    onOpenLink: () -> Unit,
) {
    val links by vm.linksFlow.collectAsState()
    val settings by vm.settingsFlow.collectAsState()

    val allCategories = stringArrayResource(R.array.page_types).toList()
    var editing by remember { mutableStateOf<WebLink?>(null) }
    var showEditor by remember { mutableStateOf(false) }
    var filter by remember { mutableStateOf(ALL_CATEGORIES) }

    val filtered = if (filter == ALL_CATEGORIES) links else links.filter { it.category == filter }

    Column(
        Modifier
            .fillMaxSize()
            .background(AdmDark),
    ) {
        AdmHeader(
            subtitle = "Gestão de links",
            trailing = {
                IconButton(onClick = onOpenSettings) {
                    Icon(
                        Icons.Filled.Settings,
                        contentDescription = "Definições",
                        tint = AdmBlack,
                    )
                }
            },
        )

        Column(
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(20.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                SectionTitle("Páginas / Links")
                Spacer(Modifier.weight(1f))
                Button(onClick = { editing = null; showEditor = true }) {
                    Text("+ Adicionar")
                }
            }
            Spacer(Modifier.height(8.dp))

            // Filtro por tipo de página (tipo de partida)
            Text("Filtrar por tipo:", color = AdmInk, fontSize = 13.sp)
            Spacer(Modifier.height(6.dp))
            Row(
                Modifier
                    .fillMaxWidth()
                    .horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                FilterChip(ALL_CATEGORIES, filter == ALL_CATEGORIES) { filter = ALL_CATEGORIES }
                allCategories.forEach { cat ->
                    FilterChip(cat, filter == cat) { filter = cat }
                }
            }
            Spacer(Modifier.height(14.dp))

            if (filtered.isEmpty()) {
                Text(
                    if (links.isEmpty()) "Ainda não existem links. Adicione o primeiro."
                    else "Nenhum link nesta categoria.",
                    color = AdmTextDim,
                )
            }
            filtered.forEach { link ->
                LinkRow(
                    link = link,
                    isHome = settings.selectedLinkId == link.id,
                    onOpen = { vm.openLink(link) { onOpenLink() } },
                    onSetHome = { vm.selectAsHome(link) },
                    onEdit = { editing = link; showEditor = true },
                    onDelete = { vm.delete(link) },
                )
                Spacer(Modifier.height(10.dp))
            }

            Spacer(Modifier.height(30.dp))
        }
    }

    if (showEditor) {
        LinkEditDialog(
            initial = editing,
            onDismiss = { showEditor = false },
            onSave = { link ->
                vm.addOrUpdate(link)
                showEditor = false
            },
        )
    }
}

@Composable
private fun FilterChip(label: String, selected: Boolean, onClick: () -> Unit) {
    if (selected) {
        Button(
            onClick = onClick,
            colors = ButtonDefaults.buttonColors(
                containerColor = AdmBlack, contentColor = AdmWhite,
            ),
        ) { Text(label) }
    } else {
        OutlinedButton(onClick = onClick) { Text(label, color = AdmInk) }
    }
}

@Composable
private fun LinkRow(
    link: WebLink,
    isHome: Boolean,
    onOpen: () -> Unit,
    onSetHome: () -> Unit,
    onEdit: () -> Unit,
    onDelete: () -> Unit,
) {
    Card(
        Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = AdmSurface),
    ) {
        Column(Modifier.padding(16.dp)) {
            // Tipo de partida em destaque.
            if (link.category.isNotBlank()) {
                Box(
                    Modifier
                        .clip(RoundedCornerShape(6.dp))
                        .background(AdmYellow)
                        .padding(horizontal = 12.dp, vertical = 5.dp),
                ) {
                    Text(
                        link.category.uppercase(),
                        color = AdmBlack,
                        fontWeight = FontWeight.Black,
                        fontSize = 14.sp,
                    )
                }
                Spacer(Modifier.height(8.dp))
            }

            Row(verticalAlignment = Alignment.CenterVertically) {
                // Área de informação clicável (abre a página). Focável pelo comando.
                Column(
                    Modifier
                        .weight(1f)
                        .clip(RoundedCornerShape(6.dp))
                        .clickable(onClick = onOpen)
                        .padding(vertical = 4.dp),
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(link.name, color = AdmText, fontWeight = FontWeight.SemiBold, fontSize = 17.sp)
                        if (isHome) {
                            Spacer(Modifier.width(8.dp))
                            Text("• INICIAL", color = AdmGreen, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                        }
                    }
                    Text(link.url, color = AdmTextDim, fontSize = 13.sp)
                    Text("OK / toque para abrir", color = AdmTextDim, fontSize = 11.sp)
                }
                IconButton(onClick = onSetHome) {
                    Icon(
                        if (isHome) Icons.Filled.Star else Icons.Outlined.StarBorder,
                        contentDescription = "Definir como inicial",
                        tint = AdmBlack,
                    )
                }
                IconButton(onClick = onEdit) {
                    Icon(Icons.Filled.Edit, contentDescription = "Editar", tint = AdmBlack)
                }
                IconButton(onClick = onDelete) {
                    Icon(Icons.Filled.Delete, contentDescription = "Eliminar", tint = AdmRed)
                }
            }
        }
    }
}

// ---- Componentes partilhados com a tela de Definições ----

@Composable
fun SectionTitle(text: String) {
    Text(
        text,
        color = AdmBlack,
        fontWeight = FontWeight.Bold,
        fontSize = 18.sp,
        modifier = Modifier.padding(bottom = 12.dp),
    )
}

@Composable
fun StepperRow(label: String, value: String, onMinus: () -> Unit, onPlus: () -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .padding(vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(label, color = AdmText, modifier = Modifier.weight(1f))
        OutlinedButton(onClick = onMinus) { Text("−", fontSize = 18.sp) }
        Box(Modifier.width(90.dp), contentAlignment = Alignment.Center) {
            Text(value, color = AdmBlack, fontWeight = FontWeight.SemiBold)
        }
        OutlinedButton(onClick = onPlus) { Text("+", fontSize = 18.sp) }
    }
}

@Composable
fun ToggleRow(label: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .padding(vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(label, color = AdmText, modifier = Modifier.weight(1f))
        androidx.compose.material3.Switch(checked = checked, onCheckedChange = onChange)
    }
}

fun formatRefresh(sec: Int): String = if (sec <= 0) "Desligado" else "${sec}s"

private val REFRESH_STEPS = listOf(0, 5, 10, 15, 30, 60, 120, 300, 600)
fun nextRefresh(cur: Int): Int {
    val i = REFRESH_STEPS.indexOfFirst { it >= cur }
    return REFRESH_STEPS.getOrElse(if (i < 0) 0 else i + 1) { REFRESH_STEPS.last() }
}
fun prevRefresh(cur: Int): Int {
    val i = REFRESH_STEPS.indexOfLast { it <= cur }
    return REFRESH_STEPS.getOrElse(if (i <= 0) 0 else i - 1) { 0 }
}
