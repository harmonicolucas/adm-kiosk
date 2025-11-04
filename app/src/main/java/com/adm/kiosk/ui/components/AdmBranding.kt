package com.adm.kiosk.ui.components

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.adm.kiosk.R
import com.adm.kiosk.ui.theme.AdmBlack
import com.adm.kiosk.ui.theme.AdmYellow

/**
 * Barra de acento ADM (amarelo com fecho preto).
 */
@Composable
fun AdmAccentBar(modifier: Modifier = Modifier, height: Int = 4) {
    Row(
        modifier
            .fillMaxWidth()
            .height(height.dp)
            .background(AdmBlack)
    ) {
        Spacer(
            Modifier
                .fillMaxWidth()
                .height((height - 1).coerceAtLeast(1).dp)
                .background(AdmYellow)
        )
    }
}

/**
 * Cabeçalho institucional com o logótipo oficial completo dos
 * Aeroportos de Moçambique, E.P. Ajusta-se automaticamente à altura do ecrã.
 */
@Composable
fun AdmHeader(
    modifier: Modifier = Modifier,
    subtitle: String? = null,
    trailing: (@Composable () -> Unit)? = null,
) {
    val config = LocalConfiguration.current
    // Logo com altura proporcional ao ecrã (entre 44dp e 96dp).
    val logoHeight = (config.screenHeightDp * 0.11f).coerceIn(44f, 96f).dp

    Column(modifier.fillMaxWidth()) {
        Row(
            Modifier
                .fillMaxWidth()
                .background(AdmYellow)
                .padding(horizontal = 20.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Image(
                painter = painterResource(R.drawable.logo_adm_mark),
                contentDescription = stringResource(R.string.adm_name),
                contentScale = ContentScale.Fit,
                modifier = Modifier.height(logoHeight),
            )
            Spacer(Modifier.width(14.dp))
            Column {
                Text(
                    text = stringResource(R.string.adm_name),
                    color = AdmBlack,
                    fontWeight = FontWeight.Black,
                    fontSize = 18.sp,
                )
                if (subtitle != null) {
                    Text(
                        text = subtitle,
                        color = AdmBlack,
                        fontWeight = FontWeight.SemiBold,
                        fontSize = 13.sp,
                    )
                }
            }
            Spacer(Modifier.weight(1f))
            if (trailing != null) trailing()
        }
        AdmAccentBar()
    }
}
