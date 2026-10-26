package tw.boardgame.recommender.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.waitForUpOrCancellation
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import tw.boardgame.recommender.ui.theme.CardBg
import tw.boardgame.recommender.ui.theme.Felt
import tw.boardgame.recommender.ui.theme.Ink
import tw.boardgame.recommender.ui.theme.Ink2
import tw.boardgame.recommender.ui.theme.Meeple
import tw.boardgame.recommender.ui.theme.Paper

/** 長按 5 秒才觸發的隱藏手勢（進入設定頁用，避免客人誤觸） */
fun Modifier.secretLongPress(onTrigger: () -> Unit, holdMillis: Long = 5000L): Modifier =
    this.pointerInput(holdMillis) {
        awaitEachGesture {
            awaitFirstDown(requireUnconsumed = false)
            // 在時限內放開或移出 → 回傳非 null；按滿時限 → 回傳 null
            val released = withTimeoutOrNull(holdMillis) {
                waitForUpOrCancellation()
                true
            }
            if (released == null) onTrigger()
        }
    }

/** 首頁：店名＋大按鈕「開始挑遊戲」 */
@Composable
fun HomeScreen(
    storeName: String,
    questionCount: Int,
    onStart: () -> Unit,
    onSecretSetup: () -> Unit
) {
    val currentSecret by rememberUpdatedState(onSecretSetup)
    val count = if (questionCount > 0) questionCount else 5

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Paper)
            .padding(24.dp),
        contentAlignment = Alignment.Center
    ) {
        Column(
            modifier = Modifier.widthIn(max = 720.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center
        ) {
            // 標誌：長按 5 秒進設定
            Box(
                modifier = Modifier
                    .size(120.dp)
                    .clip(RoundedCornerShape(32.dp))
                    .background(Felt)
                    .secretLongPress(onTrigger = { currentSecret() }),
                contentAlignment = Alignment.Center
            ) {
                Text(text = "🎲", fontSize = 64.sp)
            }
            Spacer(Modifier.height(20.dp))
            // 店名：同樣可長按 5 秒進設定
            Text(
                text = storeName.ifEmpty { "桌遊推薦" },
                style = MaterialTheme.typography.displayMedium,
                color = Ink,
                textAlign = TextAlign.Center,
                modifier = Modifier.secretLongPress(onTrigger = { currentSecret() })
            )
            Spacer(Modifier.height(8.dp))
            Text(
                text = "今天想玩什麼？讓我們幫你挑！",
                style = MaterialTheme.typography.titleMedium,
                color = Ink2,
                textAlign = TextAlign.Center
            )
            Spacer(Modifier.height(48.dp))
            BigButton(
                text = "開始挑遊戲  ▶",
                onClick = onStart,
                color = Meeple,
                contentColor = CardBg,
                minHeight = 96.dp,
                fontSize = 32.sp,
                modifier = Modifier.fillMaxWidth()
            )
            Spacer(Modifier.height(20.dp))
            Text(
                text = "回答 $count 個小問題，30 秒挑到今天的桌遊",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Normal,
                color = Ink2,
                textAlign = TextAlign.Center
            )
        }
    }
}
