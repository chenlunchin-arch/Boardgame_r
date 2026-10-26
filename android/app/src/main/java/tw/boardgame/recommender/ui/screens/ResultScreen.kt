package tw.boardgame.recommender.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import tw.boardgame.recommender.data.GameResult
import tw.boardgame.recommender.data.RecommendResult
import tw.boardgame.recommender.ui.theme.CardBg
import tw.boardgame.recommender.ui.theme.Felt
import tw.boardgame.recommender.ui.theme.FeltLight
import tw.boardgame.recommender.ui.theme.Gold
import tw.boardgame.recommender.ui.theme.Ink
import tw.boardgame.recommender.ui.theme.Ink2
import tw.boardgame.recommender.ui.theme.Line
import tw.boardgame.recommender.ui.theme.Meeple
import tw.boardgame.recommender.ui.theme.Paper

/** 結果頁：推薦清單＋教學影片按鈕＋點數提示 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ResultScreen(
    result: RecommendResult,
    answerLabels: List<String>,
    showPrice: Boolean,
    baseUrl: String,
    claimMessage: String?,
    claimSuccess: Boolean,
    onWatch: (GameResult) -> Unit,
    onRestart: () -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Paper)
    ) {
        LazyColumn(
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth(),
            contentPadding = PaddingValues(horizontal = 24.dp, vertical = 24.dp),
            verticalArrangement = Arrangement.spacedBy(18.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            // ---- 標題與答案摘要 ----
            item {
                Column(
                    modifier = Modifier.widthIn(max = 980.dp).fillMaxWidth(),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    Text(
                        text = "為你們挑好了！",
                        style = MaterialTheme.typography.headlineLarge,
                        color = Ink,
                        textAlign = TextAlign.Center
                    )
                    val m = result.member
                    if (m != null) {
                        Spacer(Modifier.height(6.dp))
                        val extra = buildString {
                            if (m.excludedCount > 0) append("已避開 ${m.excludedCount} 款玩過的遊戲")
                            if (m.personalized) {
                                if (isNotEmpty()) append("，")
                                append("依你的喜好調整")
                            }
                        }
                        val line = listOf(m.greeting, extra).filter { it.isNotEmpty() }.joinToString("　")
                        if (line.isNotEmpty()) {
                            Text(
                                text = line,
                                style = MaterialTheme.typography.titleMedium,
                                color = Felt,
                                textAlign = TextAlign.Center
                            )
                        }
                    }
                    if (answerLabels.isNotEmpty()) {
                        Spacer(Modifier.height(12.dp))
                        FlowRow(
                            horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.CenterHorizontally),
                            verticalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            for (label in answerLabels) {
                                Pill(text = label, background = FeltLight, contentColor = Felt)
                            }
                        }
                    }
                    // 點數提示卡
                    if (claimMessage != null) {
                        Spacer(Modifier.height(14.dp))
                        Box(
                            modifier = Modifier
                                .clip(RoundedCornerShape(16.dp))
                                .background(if (claimSuccess) Gold.copy(alpha = 0.25f) else Line.copy(alpha = 0.6f))
                                .border(BorderStroke(2.dp, if (claimSuccess) Gold else Line), RoundedCornerShape(16.dp))
                                .padding(horizontal = 24.dp, vertical = 12.dp)
                        ) {
                            Text(
                                text = (if (claimSuccess) "🎉 " else "") + claimMessage,
                                style = MaterialTheme.typography.titleLarge,
                                color = Ink,
                                textAlign = TextAlign.Center
                            )
                        }
                    }
                }
            }

            if (result.results.isEmpty()) {
                item {
                    Text(
                        text = "這次沒有找到合適的遊戲，請換個答案再試一次，或問問店員推薦！",
                        style = MaterialTheme.typography.titleMedium,
                        color = Ink2,
                        textAlign = TextAlign.Center,
                        modifier = Modifier.padding(top = 32.dp)
                    )
                }
            }

            // ---- 每款遊戲一張卡 ----
            itemsIndexed(result.results, key = { i, g -> "${i}_${g.id}" }) { index, game ->
                GameCard(
                    rank = index + 1,
                    game = game,
                    showPrice = showPrice,
                    baseUrl = baseUrl,
                    onWatch = { onWatch(game) },
                    modifier = Modifier.widthIn(max = 980.dp).fillMaxWidth()
                )
            }
        }

        // ---- 底部重新開始 ----
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .background(CardBg)
                .border(BorderStroke(1.dp, Line))
                .padding(horizontal = 24.dp, vertical = 12.dp),
            contentAlignment = Alignment.Center
        ) {
            BigButton(
                text = "↻ 重新開始",
                onClick = onRestart,
                color = Felt,
                modifier = Modifier.widthIn(min = 320.dp)
            )
        }
    }
}

/** 單款遊戲卡片 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun GameCard(
    rank: Int,
    game: GameResult,
    showPrice: Boolean,
    baseUrl: String,
    onWatch: () -> Unit,
    modifier: Modifier = Modifier
) {
    val isFirst = rank == 1
    val rankColor: Color = when (rank) {
        1 -> Gold
        2 -> Color(0xFFB8B2A7)
        3 -> Color(0xFFC08A5B)
        else -> Line
    }
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(24.dp))
            .background(CardBg)
            .border(
                BorderStroke(if (isFirst) 3.dp else 1.5.dp, if (isFirst) Gold else Line),
                RoundedCornerShape(24.dp)
            )
            .padding(20.dp)
    ) {
        // ---- 標頭：排名、名稱、契合度 ----
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                modifier = Modifier
                    .size(56.dp)
                    .clip(CircleShape)
                    .background(rankColor),
                contentAlignment = Alignment.Center
            ) {
                Text(
                    text = if (isFirst) "👑" else "$rank",
                    fontSize = if (isFirst) 28.sp else 24.sp,
                    fontWeight = FontWeight.Bold,
                    color = Ink
                )
            }
            Spacer(Modifier.width(14.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = if (isFirst) "第 1 名　${game.name}" else game.name,
                    style = MaterialTheme.typography.headlineMedium,
                    color = Ink
                )
                if (game.nameEn.isNotEmpty()) {
                    Text(text = game.nameEn, style = MaterialTheme.typography.bodyLarge, color = Ink2)
                }
            }
            Spacer(Modifier.width(12.dp))
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text(
                    text = "${game.matchPercent}%",
                    fontSize = 34.sp,
                    fontWeight = FontWeight.Bold,
                    color = if (isFirst) Meeple else Felt
                )
                Text(text = "契合度", style = MaterialTheme.typography.labelMedium, color = Ink2)
            }
        }

        if (game.playedBefore) {
            Spacer(Modifier.height(10.dp))
            Pill(text = "✔ 你玩過這款", background = Gold.copy(alpha = 0.3f), contentColor = Ink)
        }

        Spacer(Modifier.height(14.dp))
        Row {
            // 封面圖（有才顯示）
            val img = resolveImageUrl(baseUrl, game.imageUrl)
            if (img.isNotEmpty()) {
                Box(
                    modifier = Modifier
                        .size(132.dp)
                        .clip(RoundedCornerShape(16.dp))
                        .background(Paper)
                ) {
                    RemoteImage(url = img, contentDescription = game.name, modifier = Modifier.fillMaxSize())
                }
                Spacer(Modifier.width(16.dp))
            }
            Column(modifier = Modifier.weight(1f)) {
                // ---- 規格資訊 ----
                FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    if (game.playersText.isNotEmpty()) InfoChip("👥 ${game.playersText}")
                    if (game.timeText.isNotEmpty()) InfoChip("⏱ ${game.timeText}")
                    if (game.weightText.isNotEmpty()) InfoChip("🧠 ${game.weightText}")
                    if (game.minAge > 0) InfoChip("🧒 ${game.minAge}+ 歲")
                    if (game.shelf.isNotEmpty()) InfoChip("📍 櫃位 ${game.shelf}")
                    // 價格：後台開啟 show_price 且有庫存、價格 > 0 才顯示
                    if (showPrice && game.inStock && game.price > 0) InfoChip("💲 ${formatPrice(game.price)}")
                    if (!game.inStock) InfoChip("暫時缺貨")
                }
                // ---- tags ----
                if (game.tags.isNotEmpty()) {
                    Spacer(Modifier.height(10.dp))
                    FlowRow(
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        for (t in game.tags) {
                            Pill(text = "#$t", background = FeltLight, contentColor = Felt, fontSize = 15.sp)
                        }
                    }
                }
            }
        }

        // ---- 介紹 ----
        if (game.description.isNotEmpty()) {
            Spacer(Modifier.height(14.dp))
            Text(text = game.description, style = MaterialTheme.typography.bodyLarge, color = Ink)
        }

        // ---- 推薦理由 ----
        if (game.reasons.isNotEmpty()) {
            Spacer(Modifier.height(12.dp))
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(14.dp))
                    .background(Paper)
                    .padding(14.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                Text(text = "推薦理由", style = MaterialTheme.typography.titleMedium, color = Felt)
                for (r in game.reasons) {
                    Row {
                        Text(text = "✓ ", style = MaterialTheme.typography.bodyLarge, color = Felt)
                        Text(text = r, style = MaterialTheme.typography.bodyLarge, color = Ink)
                    }
                }
            }
        }

        // ---- 教學影片 ----
        val yt = game.youtube
        if (yt != null && (yt.videoId != null || yt.url.isNotEmpty())) {
            Spacer(Modifier.height(16.dp))
            BigButton(
                text = if (yt.videoId != null && !yt.isSearch) "▶ 看教學影片" else "▶ 搜尋教學影片",
                onClick = onWatch,
                color = Meeple,
                modifier = Modifier.fillMaxWidth()
            )
        }
    }
}

@Composable
private fun InfoChip(text: String) {
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(12.dp))
            .background(Paper)
            .border(BorderStroke(1.dp, Line), RoundedCornerShape(12.dp))
            .padding(horizontal = 12.dp, vertical = 6.dp)
    ) {
        Text(text = text, fontSize = 17.sp, color = Ink, fontWeight = FontWeight.Medium)
    }
}

/** 價格：整數不顯示小數點 */
private fun formatPrice(p: Double): String =
    if (p % 1.0 == 0.0) "${p.toLong()} 元" else String.format(java.util.Locale.US, "%.1f 元", p)
