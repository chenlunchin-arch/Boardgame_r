package tw.boardgame.recommender.ui

import android.net.Uri
import android.widget.Toast
import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import tw.boardgame.recommender.data.GameResult
import tw.boardgame.recommender.ui.screens.ErrorScreen
import tw.boardgame.recommender.ui.screens.HomeScreen
import tw.boardgame.recommender.ui.screens.LoadingScreen
import tw.boardgame.recommender.ui.screens.MemberScreen
import tw.boardgame.recommender.ui.screens.QuizScreen
import tw.boardgame.recommender.ui.screens.ResultScreen
import tw.boardgame.recommender.ui.screens.SetupScreen
import tw.boardgame.recommender.ui.screens.VideoDialog
import tw.boardgame.recommender.ui.screens.openExternalUrl
import tw.boardgame.recommender.ui.theme.Paper

/** 整個 APP 的根畫面：依 Screen 切換頁面 */
@Composable
fun BoardgameApp(vm: AppViewModel, serverUrl: () -> String) {
    val state by vm.state.collectAsStateWithLifecycle()
    val context = LocalContext.current

    // 返回鍵永遠由 APP 自己處理：問答中＝上一題，首頁不退出
    BackHandler(enabled = true) { vm.onBack() }

    // 看教學影片：有 video_id 在站內播放，否則交給瀏覽器 / YouTube App
    val onWatch: (GameResult) -> Unit = { game ->
        val yt = game.youtube
        if (yt != null) {
            if (yt.videoId != null && !yt.isSearch) {
                vm.openVideo(game.name, yt)
            } else {
                val url = yt.url.ifEmpty {
                    "https://www.youtube.com/results?search_query=" + Uri.encode("${game.name} 桌遊 教學")
                }
                if (!openExternalUrl(context, url)) {
                    Toast.makeText(context, "這台平板沒有可開啟影片的 App", Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Paper)
    ) {
        AnimatedContent(
            targetState = state.screen,
            transitionSpec = { fadeIn() togetherWith fadeOut() },
            // 同類型頁面（例如第 1 題 → 第 2 題）也做淡入淡出
            contentKey = { it },
            label = "screen"
        ) { screen ->
            when (screen) {
                is Screen.Setup -> SetupScreen(
                    ui = state.setup,
                    firstRun = screen.firstRun,
                    appVersion = AppViewModel.APP_VERSION,
                    onUrlChange = vm::setupUrlChanged,
                    onKeyChange = vm::setupKeyChanged,
                    onTest = vm::setupTest,
                    onSave = vm::setupSave,
                    onCancel = vm::setupCancel
                )

                is Screen.Home -> HomeScreen(
                    storeName = state.storeName,
                    questionCount = state.config?.questions?.size ?: 0,
                    onStart = vm::startQuiz,
                    onSecretSetup = { vm.openSetup(firstRun = false) }
                )

                is Screen.Member -> MemberScreen(
                    ui = state.member,
                    pointsPerQuiz = state.config?.pointsPerQuiz ?: 0,
                    onDigit = vm::memberKey,
                    onBackspace = vm::memberBackspace,
                    onClear = vm::memberClear,
                    onLookup = vm::memberLookup,
                    onSkip = vm::memberSkip,
                    onHome = vm::goHome
                )

                is Screen.Quiz -> {
                    val questions = state.config?.questions.orEmpty()
                    val q = questions.getOrNull(screen.index)
                    if (q == null) {
                        LoadingScreen(text = "準備題目中…")
                    } else {
                        QuizScreen(
                            question = q,
                            index = screen.index,
                            total = questions.size,
                            // 正在跳題時顯示剛點的；回到上一題時顯示之前選過的
                            selectedValue = state.pendingValue ?: state.answers[q.key],
                            onSelect = vm::selectOption,
                            onPrevious = vm::previousQuestion,
                            onHome = vm::goHome
                        )
                    }
                }

                is Screen.Loading -> LoadingScreen(text = screen.text)

                is Screen.Result -> {
                    val r = state.result
                    if (r == null) {
                        // 回首頁淡出時結果已清空，畫空白背景避免閃出其他字
                        Box(modifier = Modifier.fillMaxSize().background(Paper))
                    } else {
                        ResultScreen(
                            result = r,
                            answerLabels = answerLabels(state),
                            showPrice = state.config?.showPrice ?: false,
                            baseUrl = serverUrl(),
                            claimMessage = state.claimMessage,
                            claimSuccess = state.claimSuccess,
                            onWatch = onWatch,
                            onRestart = vm::goHome
                        )
                    }
                }

                is Screen.Error -> ErrorScreen(
                    message = screen.message,
                    isAuth = screen.isAuth,
                    isNetwork = screen.isNetwork,
                    onRetry = vm::retry,
                    onHome = vm::goHome,
                    onSetup = { vm.openSetup(firstRun = false) }
                )
            }
        }

        // 影片 Dialog（疊在結果頁上）
        val video = state.video
        if (video != null && video.youtube.videoId != null) {
            VideoDialog(video = video, onClose = vm::closeVideo)
        }
    }
}

/** 把答案轉成顯示用的文字（emoji＋label），依題目順序 */
private fun answerLabels(state: UiState): List<String> {
    val questions = state.config?.questions ?: return emptyList()
    val out = mutableListOf<String>()
    for (q in questions) {
        val v = state.answers[q.key] ?: continue
        val opt = q.options.firstOrNull { it.value == v } ?: continue
        out.add(if (opt.emoji.isNotEmpty()) "${opt.emoji} ${opt.label}" else opt.label)
    }
    return out
}
