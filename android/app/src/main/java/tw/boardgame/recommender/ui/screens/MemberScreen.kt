package tw.boardgame.recommender.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import tw.boardgame.recommender.ui.MemberUi
import tw.boardgame.recommender.ui.theme.CardBg
import tw.boardgame.recommender.ui.theme.Felt
import tw.boardgame.recommender.ui.theme.FeltLight
import tw.boardgame.recommender.ui.theme.Gold
import tw.boardgame.recommender.ui.theme.Ink
import tw.boardgame.recommender.ui.theme.Ink2
import tw.boardgame.recommender.ui.theme.Line
import tw.boardgame.recommender.ui.theme.Meeple
import tw.boardgame.recommender.ui.theme.Paper

/** 會員頁：自製數字鍵盤輸入手機（不叫出系統鍵盤，避免遮擋） */
@Composable
fun MemberScreen(
    ui: MemberUi,
    pointsPerQuiz: Int,
    onDigit: (Char) -> Unit,
    onBackspace: () -> Unit,
    onClear: () -> Unit,
    onLookup: () -> Unit,
    onSkip: () -> Unit,
    onHome: () -> Unit
) {
    BoxWithConstraints(
        modifier = Modifier
            .fillMaxSize()
            .background(Paper)
    ) {
        val landscape = maxWidth > maxHeight && maxWidth >= 700.dp
        if (landscape) {
            // 橫向：左邊說明＋輸入框，右邊鍵盤
            Row(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(32.dp),
                horizontalArrangement = Arrangement.spacedBy(40.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column(
                    modifier = Modifier
                        .weight(1f)
                        .verticalScroll(rememberScrollState()),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    MemberHeader(ui, pointsPerQuiz)
                    Spacer(Modifier.height(24.dp))
                    MemberActions(ui, onLookup, onSkip, onHome)
                }
                Box(modifier = Modifier.weight(1f), contentAlignment = Alignment.Center) {
                    NumberPad(
                        enabled = !ui.loading && ui.found == null,
                        onDigit = onDigit,
                        onBackspace = onBackspace,
                        onClear = onClear,
                        modifier = Modifier.widthIn(max = 460.dp)
                    )
                }
            }
        } else {
            // 直向：由上而下
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(24.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Column(
                    modifier = Modifier.widthIn(max = 560.dp),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    MemberHeader(ui, pointsPerQuiz)
                    Spacer(Modifier.height(20.dp))
                    NumberPad(
                        enabled = !ui.loading && ui.found == null,
                        onDigit = onDigit,
                        onBackspace = onBackspace,
                        onClear = onClear,
                        modifier = Modifier.fillMaxWidth()
                    )
                    Spacer(Modifier.height(20.dp))
                    MemberActions(ui, onLookup, onSkip, onHome)
                }
            }
        }
    }
}

/** 標題、輸入顯示框、訊息 */
@Composable
private fun MemberHeader(ui: MemberUi, pointsPerQuiz: Int) {
    Text(
        text = "是會員嗎？",
        style = MaterialTheme.typography.headlineLarge,
        color = Ink,
        textAlign = TextAlign.Center
    )
    Spacer(Modifier.height(6.dp))
    val pointsText = if (pointsPerQuiz > 0) "＋領 $pointsPerQuiz 點" else ""
    Text(
        text = "輸入手機，避開玩過的遊戲$pointsText",
        style = MaterialTheme.typography.titleMedium,
        color = Ink2,
        textAlign = TextAlign.Center
    )
    Spacer(Modifier.height(20.dp))

    // 輸入顯示框
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = 80.dp)
            .clip(RoundedCornerShape(18.dp))
            .background(CardBg)
            .border(BorderStroke(2.dp, if (ui.found != null) Felt else Line), RoundedCornerShape(18.dp))
            .padding(horizontal = 20.dp, vertical = 12.dp),
        contentAlignment = Alignment.Center
    ) {
        Text(
            text = ui.input.ifEmpty { "09xx-xxx-xxx" },
            fontSize = 38.sp,
            fontWeight = FontWeight.Bold,
            letterSpacing = 3.sp,
            color = if (ui.input.isEmpty()) Line else Ink,
            textAlign = TextAlign.Center
        )
    }

    // 查詢結果 / 錯誤訊息
    val found = ui.found
    if (found != null) {
        Spacer(Modifier.height(16.dp))
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(18.dp))
                .background(FeltLight)
                .padding(18.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Text(
                text = found.greeting.ifEmpty { "歡迎回來！" },
                style = MaterialTheme.typography.titleLarge,
                color = Felt,
                textAlign = TextAlign.Center
            )
            Spacer(Modifier.height(4.dp))
            Text(
                text = "目前點數 ${found.points} 點　馬上開始…",
                style = MaterialTheme.typography.titleMedium,
                color = Ink2,
                textAlign = TextAlign.Center
            )
        }
    } else if (ui.message.isNotEmpty()) {
        Spacer(Modifier.height(12.dp))
        Text(
            text = ui.message,
            style = MaterialTheme.typography.titleMedium,
            color = Meeple,
            textAlign = TextAlign.Center
        )
    }
}

/** 查詢 / 略過 / 回首頁 */
@Composable
private fun MemberActions(
    ui: MemberUi,
    onLookup: () -> Unit,
    onSkip: () -> Unit,
    onHome: () -> Unit
) {
    if (ui.loading) {
        CircularProgressIndicator(color = Felt, modifier = Modifier.size(56.dp))
        Spacer(Modifier.height(16.dp))
    }
    ButtonRow(modifier = Modifier.fillMaxWidth()) {
        BigButton(
            text = "查詢",
            onClick = onLookup,
            enabled = !ui.loading && ui.found == null && ui.input.isNotEmpty(),
            modifier = Modifier.weight(1f)
        )
        SecondaryButton(
            text = "略過，直接開始",
            onClick = onSkip,
            enabled = ui.found == null,
            modifier = Modifier.weight(1f)
        )
    }
    Spacer(Modifier.height(12.dp))
    SecondaryButton(text = "回首頁", onClick = onHome, minHeight = 64.dp, modifier = Modifier.fillMaxWidth())
}

/** 3x4 數字鍵盤：1-9、清除、0、刪除 */
@Composable
fun NumberPad(
    enabled: Boolean,
    onDigit: (Char) -> Unit,
    onBackspace: () -> Unit,
    onClear: () -> Unit,
    modifier: Modifier = Modifier
) {
    val rows = listOf(
        listOf("1", "2", "3"),
        listOf("4", "5", "6"),
        listOf("7", "8", "9"),
        listOf("清除", "0", "⌫")
    )
    Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(12.dp)) {
        for (row in rows) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                for (k in row) {
                    val isAction = k == "清除" || k == "⌫"
                    Button(
                        onClick = {
                            when (k) {
                                "清除" -> onClear()
                                "⌫" -> onBackspace()
                                else -> onDigit(k[0])
                            }
                        },
                        enabled = enabled,
                        modifier = Modifier
                            .weight(1f)
                            .height(76.dp),
                        shape = RoundedCornerShape(16.dp),
                        colors = ButtonDefaults.buttonColors(
                            containerColor = if (isAction) Gold.copy(alpha = 0.25f) else CardBg,
                            contentColor = Ink,
                            disabledContainerColor = Line.copy(alpha = 0.5f),
                            disabledContentColor = Ink2
                        ),
                        border = BorderStroke(1.5.dp, Line),
                        elevation = ButtonDefaults.buttonElevation(defaultElevation = 1.dp)
                    ) {
                        Text(
                            text = k,
                            fontSize = if (isAction) 22.sp else 32.sp,
                            fontWeight = FontWeight.Bold,
                            color = if (enabled) Ink else Ink2
                        )
                    }
                }
            }
        }
    }
}
