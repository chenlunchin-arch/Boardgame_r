package tw.boardgame.recommender.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import tw.boardgame.recommender.ui.SetupUi
import tw.boardgame.recommender.ui.theme.CardBg
import tw.boardgame.recommender.ui.theme.Felt
import tw.boardgame.recommender.ui.theme.Ink
import tw.boardgame.recommender.ui.theme.Ink2
import tw.boardgame.recommender.ui.theme.Line
import tw.boardgame.recommender.ui.theme.Meeple
import tw.boardgame.recommender.ui.theme.Paper

/** 設定頁（店員用）：伺服器網址、配對碼、測試連線、儲存 */
@Composable
fun SetupScreen(
    ui: SetupUi,
    firstRun: Boolean,
    appVersion: String,
    onUrlChange: (String) -> Unit,
    onKeyChange: (String) -> Unit,
    onTest: () -> Unit,
    onSave: () -> Unit,
    onCancel: () -> Unit
) {
    val fieldColors = OutlinedTextFieldDefaults.colors(
        focusedBorderColor = Felt,
        unfocusedBorderColor = Line,
        focusedContainerColor = CardBg,
        unfocusedContainerColor = CardBg,
        focusedLabelColor = Felt,
        cursorColor = Felt
    )
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Paper)
            .imePadding()
            .verticalScroll(rememberScrollState())
            .padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Column(
            modifier = Modifier.widthIn(max = 640.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            Text(text = "⚙️", fontSize = 56.sp)
            Text(
                text = "平板設定（店員專用）",
                style = MaterialTheme.typography.headlineLarge,
                color = Ink,
                textAlign = TextAlign.Center
            )
            Text(
                text = if (firstRun) "第一次使用，請輸入櫃檯電腦的伺服器網址與後台「平板配對」取得的配對碼。"
                else "修改後請先「測試連線」，成功才能儲存。",
                style = MaterialTheme.typography.bodyLarge,
                color = Ink2,
                textAlign = TextAlign.Center
            )

            OutlinedTextField(
                value = ui.url,
                onValueChange = onUrlChange,
                label = { Text("伺服器網址") },
                placeholder = { Text("http://192.168.1.10:5000") },
                singleLine = true,
                textStyle = TextStyle(fontSize = 22.sp, color = Ink),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Next),
                colors = fieldColors,
                modifier = Modifier.fillMaxWidth()
            )
            OutlinedTextField(
                value = ui.key,
                onValueChange = onKeyChange,
                label = { Text("平板配對碼") },
                placeholder = { Text("後台 → 平板配對 → 新增裝置") },
                singleLine = true,
                textStyle = TextStyle(fontSize = 22.sp, color = Ink),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Ascii, imeAction = ImeAction.Done),
                colors = fieldColors,
                modifier = Modifier.fillMaxWidth()
            )

            if (ui.testing) {
                CircularProgressIndicator(color = Felt, modifier = Modifier.size(48.dp))
            }
            if (ui.message.isNotEmpty()) {
                Text(
                    text = ui.message,
                    style = MaterialTheme.typography.titleMedium,
                    color = if (ui.success) Felt else Meeple,
                    textAlign = TextAlign.Center
                )
            }

            BigButton(
                text = "測試連線",
                onClick = onTest,
                enabled = !ui.testing,
                modifier = Modifier.fillMaxWidth()
            )
            ButtonRow(modifier = Modifier.fillMaxWidth()) {
                BigButton(
                    text = "儲存",
                    onClick = onSave,
                    enabled = ui.canSave && !ui.testing,
                    color = Meeple,
                    modifier = Modifier.weight(1f)
                )
                if (!firstRun) {
                    SecondaryButton(text = "取消", onClick = onCancel, modifier = Modifier.weight(1f))
                }
            }
            Spacer(Modifier.height(8.dp))
            Text(
                text = "APP 版本 $appVersion　｜　首頁長按店名或骰子 5 秒可再次進入此頁",
                style = MaterialTheme.typography.labelMedium,
                color = Ink2,
                textAlign = TextAlign.Center
            )
        }
    }
}
