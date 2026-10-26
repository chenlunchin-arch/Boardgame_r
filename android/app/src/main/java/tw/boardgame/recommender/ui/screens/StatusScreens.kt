package tw.boardgame.recommender.ui.screens

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.draw.scale
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import tw.boardgame.recommender.ui.theme.Felt
import tw.boardgame.recommender.ui.theme.Ink
import tw.boardgame.recommender.ui.theme.Ink2
import tw.boardgame.recommender.ui.theme.Line
import tw.boardgame.recommender.ui.theme.Meeple
import tw.boardgame.recommender.ui.theme.Paper

/** 載入中：旋轉的骰子＋文字 */
@Composable
fun LoadingScreen(text: String) {
    val transition = rememberInfiniteTransition(label = "dice")
    val angle by transition.animateFloat(
        initialValue = 0f,
        targetValue = 360f,
        animationSpec = infiniteRepeatable(animation = tween(1200, easing = LinearEasing)),
        label = "angle"
    )
    val pulse by transition.animateFloat(
        initialValue = 0.9f,
        targetValue = 1.1f,
        animationSpec = infiniteRepeatable(animation = tween(600), repeatMode = RepeatMode.Reverse),
        label = "pulse"
    )
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Paper),
        contentAlignment = Alignment.Center
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(
                text = "🎲",
                fontSize = 96.sp,
                modifier = Modifier
                    .scale(pulse)
                    .rotate(angle)
            )
            Spacer(Modifier.height(28.dp))
            Text(
                text = text,
                style = MaterialTheme.typography.headlineMedium,
                color = Ink,
                textAlign = TextAlign.Center
            )
            Spacer(Modifier.height(20.dp))
            LinearProgressIndicator(
                modifier = Modifier.widthIn(min = 200.dp, max = 320.dp),
                color = Felt,
                trackColor = Line
            )
        }
    }
}

/** 錯誤頁：友善訊息＋重試 / 回首頁 / 設定 */
@Composable
fun ErrorScreen(
    message: String,
    isAuth: Boolean,
    isNetwork: Boolean,
    onRetry: () -> Unit,
    onHome: () -> Unit,
    onSetup: () -> Unit
) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Paper)
            .padding(32.dp),
        contentAlignment = Alignment.Center
    ) {
        // 捲動放在內層，內容較少時仍可垂直置中
        Column(
            modifier = Modifier
                .widthIn(max = 640.dp)
                .verticalScroll(rememberScrollState()),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center
        ) {
            Text(text = if (isAuth) "🔑" else if (isNetwork) "📡" else "😅", fontSize = 80.sp)
            Spacer(Modifier.height(16.dp))
            Text(
                text = when {
                    isAuth -> "平板尚未配對成功"
                    isNetwork -> "哎呀，暫時連不到櫃檯"
                    else -> "櫃檯系統回報了一個問題"
                },
                style = MaterialTheme.typography.headlineLarge,
                color = Ink,
                textAlign = TextAlign.Center
            )
            Spacer(Modifier.height(12.dp))
            Text(
                text = when {
                    isAuth -> "請店員到設定頁重新輸入配對碼。"
                    isNetwork -> "請稍等一下再試一次，或請店員協助檢查網路。"
                    else -> "請再試一次，若持續發生請洽櫃檯人員。"
                },
                style = MaterialTheme.typography.titleMedium,
                color = Ink2,
                textAlign = TextAlign.Center
            )
            Spacer(Modifier.height(8.dp))
            Text(
                text = message,
                style = MaterialTheme.typography.bodyMedium,
                color = Meeple,
                textAlign = TextAlign.Center
            )
            Spacer(Modifier.height(32.dp))
            BigButton(text = "重試", onClick = onRetry, modifier = Modifier.fillMaxWidth())
            Spacer(Modifier.height(14.dp))
            ButtonRow(modifier = Modifier.fillMaxWidth()) {
                SecondaryButton(text = "回首頁", onClick = onHome, modifier = Modifier.weight(1f))
                SecondaryButton(text = "設定（店員）", onClick = onSetup, modifier = Modifier.weight(1f))
            }
        }
    }
}
