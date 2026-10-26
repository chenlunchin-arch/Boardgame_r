package tw.boardgame.recommender.ui.screens

import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import tw.boardgame.recommender.data.QuizOption
import tw.boardgame.recommender.data.QuizQuestion
import tw.boardgame.recommender.ui.theme.CardBg
import tw.boardgame.recommender.ui.theme.Felt
import tw.boardgame.recommender.ui.theme.FeltLight
import tw.boardgame.recommender.ui.theme.Ink
import tw.boardgame.recommender.ui.theme.Ink2
import tw.boardgame.recommender.ui.theme.Line
import tw.boardgame.recommender.ui.theme.Paper

/** 問答頁：進度條＋題目＋大卡片選項 */
@Composable
fun QuizScreen(
    question: QuizQuestion,
    index: Int,
    total: Int,
    selectedValue: String?,
    onSelect: (String) -> Unit,
    onPrevious: () -> Unit,
    onHome: () -> Unit
) {
    BoxWithConstraints(
        modifier = Modifier
            .fillMaxSize()
            .background(Paper)
    ) {
        // 平板橫向 3 欄，其餘 2 欄；選項很少時不超過選項數
        val wide = maxWidth >= 840.dp || (maxWidth > maxHeight && maxWidth >= 640.dp)
        val columns = (if (wide) 3 else 2).coerceAtMost(question.options.size.coerceAtLeast(1))

        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 24.dp, vertical = 20.dp)
        ) {
            // ---- 進度 ----
            val progress = if (total > 0) (index + 1).toFloat() / total else 0f
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = "第 ${index + 1} / $total 題",
                    style = MaterialTheme.typography.titleMedium,
                    color = Felt
                )
                Spacer(Modifier.weight(1f))
                Text(
                    text = "回首頁",
                    style = MaterialTheme.typography.titleMedium,
                    color = Ink2,
                    modifier = Modifier
                        .clip(RoundedCornerShape(12.dp))
                        .clickable(onClick = onHome)
                        .padding(horizontal = 16.dp, vertical = 12.dp)
                )
            }
            Spacer(Modifier.height(8.dp))
            LinearProgressIndicator(
                progress = { progress },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(12.dp)
                    .clip(RoundedCornerShape(6.dp)),
                color = Felt,
                trackColor = Line
            )

            // ---- 題目與選項（可捲動） ----
            Column(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .verticalScroll(rememberScrollState()),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Spacer(Modifier.height(28.dp))
                Text(
                    text = question.title,
                    style = MaterialTheme.typography.headlineLarge,
                    color = Ink,
                    textAlign = TextAlign.Center
                )
                if (question.subtitle.isNotEmpty()) {
                    Spacer(Modifier.height(8.dp))
                    Text(
                        text = question.subtitle,
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Normal,
                        color = Ink2,
                        textAlign = TextAlign.Center
                    )
                }
                Spacer(Modifier.height(28.dp))

                Column(
                    modifier = Modifier
                        .widthIn(max = 1100.dp)
                        .fillMaxWidth(),
                    verticalArrangement = Arrangement.spacedBy(16.dp)
                ) {
                    for (rowItems in question.options.chunked(columns)) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(16.dp)
                        ) {
                            for (opt in rowItems) {
                                OptionCard(
                                    option = opt,
                                    selected = opt.value == selectedValue,
                                    onClick = { onSelect(opt.value) },
                                    modifier = Modifier.weight(1f)
                                )
                            }
                            // 最後一排補空位，讓卡片寬度一致
                            repeat(columns - rowItems.size) {
                                Spacer(Modifier.weight(1f))
                            }
                        }
                    }
                }
                Spacer(Modifier.height(24.dp))
            }

            // ---- 上一題 ----
            SecondaryButton(
                text = "◀ 上一題",
                onClick = onPrevious,
                modifier = Modifier.widthIn(min = 200.dp)
            )
        }
    }
}

/** 單一選項大卡片：emoji 大字＋文字 */
@Composable
private fun OptionCard(
    option: QuizOption,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    val bg by animateColorAsState(if (selected) FeltLight else CardBg, label = "optBg")
    val borderColor by animateColorAsState(if (selected) Felt else Line, label = "optBorder")
    Box(
        modifier = modifier
            .heightIn(min = 150.dp)
            .clip(RoundedCornerShape(22.dp))
            .background(bg)
            .border(BorderStroke(if (selected) 4.dp else 2.dp, borderColor), RoundedCornerShape(22.dp))
            .clickable(onClick = onClick)
            .padding(16.dp),
        contentAlignment = Alignment.Center
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            if (option.emoji.isNotEmpty()) {
                Text(text = option.emoji, fontSize = 52.sp, textAlign = TextAlign.Center)
                Spacer(Modifier.height(8.dp))
            }
            Text(
                text = option.label,
                fontSize = 24.sp,
                fontWeight = FontWeight.Bold,
                color = if (selected) Felt else Ink,
                textAlign = TextAlign.Center,
                lineHeight = 30.sp
            )
        }
    }
}
