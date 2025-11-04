package com.adm.kiosk.ui.kiosk

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.adm.kiosk.R
import com.adm.kiosk.ui.theme.AdmBlack
import com.adm.kiosk.ui.theme.AdmInkDim
import com.adm.kiosk.ui.theme.AdmWhite
import com.adm.kiosk.ui.theme.AdmYellow

enum class OverlayState { Splash, Loading, Offline, NoLinks, None }

/** Painel pedido pelo administrador web para saber fisicamente qual é este televisor. */
@Composable
fun IdentifyBanner(text: String) {
    val config = LocalConfiguration.current
    val minDim = minOf(config.screenWidthDp, config.screenHeightDp)
    val lines = text.lines()
    Box(
        Modifier
            .fillMaxSize()
            .background(AdmBlack.copy(alpha = 0.55f)),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            Modifier
                .clip(RoundedCornerShape(20.dp))
                .background(AdmYellow)
                .padding(horizontal = 48.dp, vertical = 32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                lines.firstOrNull().orEmpty(),
                color = AdmBlack,
                fontWeight = FontWeight.Black,
                fontSize = (minDim * 0.08f).coerceIn(28f, 80f).sp,
                textAlign = TextAlign.Center,
            )
            lines.drop(1).forEach {
                Spacer(Modifier.height(8.dp))
                Text(
                    it,
                    color = AdmBlack,
                    fontWeight = FontWeight.Bold,
                    fontSize = (minDim * 0.035f).coerceIn(16f, 36f).sp,
                    textAlign = TextAlign.Center,
                )
            }
        }
    }
}

@Composable
fun KioskOverlay(
    state: OverlayState,
    onOpenAdmin: () -> Unit,
) {
    if (state == OverlayState.None) return

    val config = LocalConfiguration.current
    val minDim = minOf(config.screenWidthDp, config.screenHeightDp)
    // Tamanhos proporcionais ao ecrã (responsivo a HD/FHD/2K/4K/projetores).
    val titleSize = (minDim * 0.05f).coerceIn(18f, 44f).sp
    val bodySize = (minDim * 0.03f).coerceIn(13f, 26f).sp

    Box(
        Modifier
            .fillMaxSize()
            .background(AdmWhite),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            val logoSize = (minDim * 0.28f).coerceIn(120f, 320f).dp
            Image(
                painter = painterResource(R.drawable.logo_adm_mark),
                contentDescription = stringResource(R.string.adm_name),
                contentScale = ContentScale.Fit,
                modifier = Modifier
                    .size(logoSize)
                    .clip(RoundedCornerShape(24.dp)),
            )
            Spacer(Modifier.height((minDim * 0.025f).dp))
            Text(
                text = stringResource(R.string.adm_name),
                color = AdmBlack,
                fontWeight = FontWeight.Black,
                fontSize = titleSize,
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height((minDim * 0.03f).dp))

            when (state) {
                OverlayState.Loading, OverlayState.Splash -> {
                    CircularProgressIndicator(color = AdmBlack)
                    Spacer(Modifier.height(12.dp))
                    Text("A carregar…", color = AdmBlack, fontSize = bodySize)
                }
                OverlayState.Offline -> {
                    Text(
                        "Sem ligação à Internet",
                        color = AdmBlack,
                        fontWeight = FontWeight.Bold,
                        fontSize = titleSize,
                    )
                    Spacer(Modifier.height(6.dp))
                    Text(
                        "A tentar restabelecer a ligação automaticamente…",
                        color = AdmBlack,
                        fontSize = bodySize,
                        textAlign = TextAlign.Center,
                    )
                }
                OverlayState.NoLinks -> {
                    Text(
                        "Nenhuma página configurada",
                        color = AdmBlack,
                        fontWeight = FontWeight.Bold,
                        fontSize = titleSize,
                    )
                    Spacer(Modifier.height(6.dp))
                    Text(
                        "Prima MENU, BACK 2× ou toque 4× no ecrã para abrir a administração.",
                        color = AdmBlack,
                        fontSize = bodySize,
                        textAlign = TextAlign.Center,
                    )
                }
                else -> {}
            }
        }

        Column(
            Modifier
                .align(Alignment.BottomCenter)
                .padding(bottom = (minDim * 0.04f).coerceIn(12f, 40f).dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                "Desenvolvido por",
                color = AdmInkDim,
                fontSize = (bodySize.value * 0.6f).sp,
            )
            Text(
                "Harmonico Lucas",
                color = AdmBlack,
                fontWeight = FontWeight.Black,
                fontSize = (bodySize.value * 0.9f).sp,
                letterSpacing = 1.5.sp,
            )
        }
    }
}
