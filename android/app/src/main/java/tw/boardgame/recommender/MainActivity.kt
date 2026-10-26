package tw.boardgame.recommender

import android.os.Bundle
import android.view.MotionEvent
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import tw.boardgame.recommender.data.Prefs
import tw.boardgame.recommender.ui.AppViewModel
import tw.boardgame.recommender.ui.BoardgameApp
import tw.boardgame.recommender.ui.theme.BoardgameTheme

/** 唯一的 Activity：全螢幕、螢幕常亮、所有畫面由 Compose 繪製 */
class MainActivity : ComponentActivity() {

    private val vm: AppViewModel by viewModels()
    private lateinit var prefs: Prefs

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)

        // 店內平板：螢幕保持常亮
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        hideSystemBars()

        setContent {
            BoardgameTheme {
                BoardgameApp(vm = vm, serverUrl = { prefs.serverUrl })
            }
        }
    }

    /** 沉浸模式：隱藏狀態列與導覽列，從邊緣滑動才暫時出現 */
    private fun hideSystemBars() {
        val controller = WindowCompat.getInsetsController(window, window.decorView)
        controller.systemBarsBehavior =
            WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        controller.hide(WindowInsetsCompat.Type.systemBars())
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        // 關掉 Dialog / 鍵盤後重新隱藏系統列
        if (hasFocus) hideSystemBars()
    }

    override fun onResume() {
        super.onResume()
        hideSystemBars()
    }

    override fun onStart() {
        super.onStart()
        vm.setAppVisible(true)
    }

    override fun onStop() {
        super.onStop()
        // 跳到 YouTube App 時暫停閒置計時
        vm.setAppVisible(false)
    }

    /** 任何觸控都重設閒置計時 */
    override fun dispatchTouchEvent(ev: MotionEvent): Boolean {
        vm.onUserInteraction()
        return super.dispatchTouchEvent(ev)
    }
}
