package tw.boardgame.recommender.ui.screens

import android.annotation.SuppressLint
import android.graphics.Color as AndroidColor
import android.view.ViewGroup
import android.webkit.WebChromeClient
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import tw.boardgame.recommender.ui.VideoUi
import tw.boardgame.recommender.ui.theme.CardBg
import tw.boardgame.recommender.ui.theme.Felt
import tw.boardgame.recommender.ui.theme.Meeple

/** 組出含 YouTube iframe 的 HTML（16:9 置中，黑底） */
private fun embedHtml(videoId: String): String {
    val src = "https://www.youtube-nocookie.com/embed/$videoId?autoplay=1&rel=0&playsinline=1"
    return """
        <!DOCTYPE html>
        <html><head>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
          html,body{margin:0;padding:0;height:100%;background:#000;overflow:hidden;}
          .wrap{position:absolute;top:0;left:0;right:0;bottom:0;display:flex;align-items:center;justify-content:center;}
          .box{position:relative;width:100%;max-width:calc(100vh * 16 / 9);aspect-ratio:16/9;}
          iframe{position:absolute;top:0;left:0;width:100%;height:100%;border:0;}
        </style></head>
        <body><div class="wrap"><div class="box">
        <iframe src="$src" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen></iframe>
        </div></div></body></html>
    """.trimIndent()
}

/** 全螢幕影片播放 Dialog（站內 WebView 播放 YouTube 教學） */
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun VideoDialog(
    video: VideoUi,
    onClose: () -> Unit
) {
    val context = LocalContext.current
    val videoId = video.youtube.videoId ?: return

    Dialog(
        onDismissRequest = onClose,
        properties = DialogProperties(
            usePlatformDefaultWidth = false,
            dismissOnBackPress = true,
            dismissOnClickOutside = false
        )
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .background(Color.Black)
        ) {
            // 上方工具列：標題＋用 YouTube App 開啟＋關閉
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(Felt)
                    .padding(horizontal = 16.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = "▶ ${video.gameName} 教學",
                    color = CardBg,
                    fontSize = 22.sp,
                    fontWeight = FontWeight.Bold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f)
                )
                Spacer(Modifier.width(12.dp))
                SecondaryButton(
                    text = "用 YouTube App 開啟",
                    onClick = {
                        val ok = openExternalUrl(context, "https://www.youtube.com/watch?v=$videoId")
                        // 交給 YouTube App 後關掉站內播放，否則 WebView 會在背景繼續出聲（兩邊同時播）
                        if (ok) onClose()
                        else Toast.makeText(context, "找不到可以開啟影片的 App", Toast.LENGTH_SHORT).show()
                    },
                    fontSize = 18.sp
                )
                Spacer(Modifier.width(12.dp))
                BigButton(text = "✕ 關閉", onClick = onClose, color = Meeple, fontSize = 20.sp)
            }

            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f),
                contentAlignment = Alignment.Center
            ) {
                AndroidView(
                    factory = { ctx ->
                        WebView(ctx).apply {
                            layoutParams = ViewGroup.LayoutParams(
                                ViewGroup.LayoutParams.MATCH_PARENT,
                                ViewGroup.LayoutParams.MATCH_PARENT
                            )
                            setBackgroundColor(AndroidColor.BLACK)
                            settings.javaScriptEnabled = true
                            settings.domStorageEnabled = true
                            settings.mediaPlaybackRequiresUserGesture = false
                            settings.loadWithOverviewMode = true
                            settings.useWideViewPort = true
                            settings.cacheMode = WebSettings.LOAD_DEFAULT
                            webChromeClient = WebChromeClient()
                            webViewClient = WebViewClient()
                            loadDataWithBaseURL(
                                "https://www.youtube-nocookie.com",
                                embedHtml(videoId),
                                "text/html",
                                "utf-8",
                                null
                            )
                        }
                    },
                    onRelease = { webView ->
                        // 關閉時停止播放並釋放 WebView
                        webView.stopLoading()
                        webView.loadUrl("about:blank")
                        webView.destroy()
                    },
                    modifier = Modifier.fillMaxSize()
                )
            }
        }
    }
}
