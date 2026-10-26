package tw.boardgame.recommender.ui

import android.app.Application
import android.os.SystemClock
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import tw.boardgame.recommender.data.ApiClient
import tw.boardgame.recommender.data.ApiException
import tw.boardgame.recommender.data.AppConfig
import tw.boardgame.recommender.data.LookupResult
import tw.boardgame.recommender.data.MemberInfo
import tw.boardgame.recommender.data.Prefs
import tw.boardgame.recommender.data.RecommendResult
import tw.boardgame.recommender.data.YoutubeInfo

/** 目前顯示哪一頁 */
sealed class Screen {
    /** 設定頁；firstRun = 第一次啟動（不能取消） */
    data class Setup(val firstRun: Boolean) : Screen()
    data object Home : Screen()
    data object Member : Screen()
    /** 問答頁，index 從 0 開始 */
    data class Quiz(val index: Int) : Screen()
    data class Loading(val text: String) : Screen()
    data object Result : Screen()
    data class Error(val message: String, val isAuth: Boolean, val isNetwork: Boolean) : Screen()
}

/** 會員頁狀態 */
data class MemberUi(
    val input: String = "",
    val loading: Boolean = false,
    val message: String = "",
    val found: MemberInfo? = null
)

/** 設定頁狀態 */
data class SetupUi(
    val url: String = "",
    val key: String = "",
    val testing: Boolean = false,
    /** 最近一次測試成功的網址＋配對碼；與目前輸入相同才可儲存 */
    val testedUrl: String? = null,
    val testedKey: String? = null,
    val message: String = "",
    val success: Boolean = false
) {
    val canSave: Boolean
        get() = success && testedUrl == ApiClient.normalizeUrl(url) && testedKey == key.trim()
}

/** 正在播放的影片 */
data class VideoUi(
    val gameName: String,
    val youtube: YoutubeInfo
)

/** 整個 APP 的畫面狀態 */
data class UiState(
    val screen: Screen = Screen.Home,
    val storeName: String = "",
    val config: AppConfig? = null,
    val member: MemberUi = MemberUi(),
    /** 題目 key → 選項 value */
    val answers: Map<String, String> = emptyMap(),
    /** 剛點下、正在等 250ms 跳題的選項（顯示選取效果） */
    val pendingValue: String? = null,
    val result: RecommendResult? = null,
    /** 領點數結果提示（null = 尚無） */
    val claimMessage: String? = null,
    val claimSuccess: Boolean = false,
    val video: VideoUi? = null,
    val setup: SetupUi = SetupUi()
) {
    /** 目前會員編號（有查到才有） */
    val memberNo: String? get() = member.found?.memberNo
}

class AppViewModel(app: Application) : AndroidViewModel(app) {

    companion object {
        const val IDLE_MS = 90_000L          // 一般頁面閒置 90 秒回首頁
        const val IDLE_RESULT_MS = 180_000L  // 結果頁閒置 180 秒
        const val NEXT_DELAY_MS = 250L       // 點選後自動跳題延遲
        const val APP_VERSION = "2.0"
    }

    private val prefs = Prefs(app)
    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state.asStateFlow()

    private var lastTouch = SystemClock.elapsedRealtime()
    private var appVisible = true
    private var nextJob: Job? = null
    private var memberJob: Job? = null
    private var claimJob: Job? = null
    private var retryAction: (() -> Unit)? = null

    private fun api(): ApiClient = ApiClient(prefs.serverUrl, prefs.deviceKey)

    init {
        _state.update { it.copy(storeName = prefs.lastStoreName) }
        if (!prefs.isConfigured) {
            openSetup(firstRun = true)
        } else {
            _state.update { it.copy(screen = Screen.Home) }
            refreshConfigSilently()
        }
        startIdleWatcher()
    }

    // ================= 閒置計時 =================

    /** 任何觸控都呼叫（MainActivity.dispatchTouchEvent） */
    fun onUserInteraction() {
        lastTouch = SystemClock.elapsedRealtime()
    }

    /** APP 前景/背景切換（去 YouTube App 時暫停計時） */
    fun setAppVisible(visible: Boolean) {
        appVisible = visible
        lastTouch = SystemClock.elapsedRealtime()
    }

    private fun startIdleWatcher() {
        viewModelScope.launch {
            while (true) {
                delay(1000)
                val s = _state.value
                // 播影片中、APP 在背景：暫停計時
                if (s.video != null || !appVisible) {
                    lastTouch = SystemClock.elapsedRealtime()
                    continue
                }
                val limit = when (s.screen) {
                    is Screen.Member, is Screen.Quiz, is Screen.Error -> IDLE_MS
                    is Screen.Result -> IDLE_RESULT_MS
                    else -> -1L // 首頁、設定、載入中不計時
                }
                if (limit > 0 && SystemClock.elapsedRealtime() - lastTouch > limit) {
                    goHome()
                }
            }
        }
    }

    // ================= 首頁 / 返回 =================

    /** 回首頁並清掉這位客人的所有資料 */
    fun goHome() {
        nextJob?.cancel()
        memberJob?.cancel()
        // 上一位客人的領點請求若還沒回來，取消掉，避免訊息顯示到下一位客人的結果頁
        claimJob?.cancel()
        retryAction = null
        _state.update {
            it.copy(
                screen = Screen.Home,
                member = MemberUi(),
                answers = emptyMap(),
                pendingValue = null,
                result = null,
                claimMessage = null,
                claimSuccess = false,
                video = null
            )
        }
        onUserInteraction()
    }

    /** 實體返回鍵：問答中＝上一題；首頁不退出 APP */
    fun onBack() {
        when (val sc = _state.value.screen) {
            is Screen.Quiz -> previousQuestion()
            is Screen.Member, is Screen.Result, is Screen.Error -> goHome()
            is Screen.Setup -> if (!sc.firstRun) goHome()
            else -> Unit // 首頁、載入中：什麼都不做
        }
    }

    /** 開始挑遊戲：每次都重新抓設定，讓後台改的題目立即生效 */
    fun startQuiz() {
        // 首頁淡出動畫期間按鈕仍可點，防止連點送出兩次
        if (_state.value.screen is Screen.Loading) return
        _state.update { it.copy(screen = Screen.Loading("準備題目中…")) }
        retryAction = { startQuiz() }
        viewModelScope.launch {
            try {
                val cfg = api().getConfig()
                applyConfig(cfg)
                if (cfg.questions.isEmpty()) {
                    showError("伺服器目前沒有設定任何題目，請洽櫃檯人員。", isAuth = false, isNetwork = false)
                    return@launch
                }
                _state.update {
                    it.copy(
                        answers = emptyMap(),
                        member = MemberUi(),
                        result = null,
                        claimMessage = null,
                        screen = if (cfg.allowMember) Screen.Member else Screen.Quiz(0)
                    )
                }
            } catch (e: ApiException) {
                showError(e.message ?: "連線失敗", e.isAuth, e.isNetwork)
            }
        }
    }

    private fun refreshConfigSilently() {
        viewModelScope.launch {
            try {
                applyConfig(api().getConfig())
            } catch (e: ApiException) {
                // 首頁先不打擾客人，按「開始」時才顯示錯誤
            }
        }
    }

    private fun applyConfig(cfg: AppConfig) {
        if (cfg.storeName.isNotEmpty()) prefs.lastStoreName = cfg.storeName
        _state.update {
            it.copy(config = cfg, storeName = cfg.storeName.ifEmpty { it.storeName })
        }
    }

    // ================= 會員 =================

    fun memberKey(digit: Char) {
        _state.update {
            if (it.member.loading || it.member.found != null || it.member.input.length >= 12) it
            else it.copy(member = it.member.copy(input = it.member.input + digit, message = ""))
        }
    }

    fun memberBackspace() {
        _state.update {
            if (it.member.loading || it.member.found != null) it
            else it.copy(member = it.member.copy(input = it.member.input.dropLast(1), message = ""))
        }
    }

    fun memberClear() {
        _state.update {
            if (it.member.loading || it.member.found != null) it
            else it.copy(member = it.member.copy(input = "", message = ""))
        }
    }

    fun memberLookup() {
        val cur = _state.value.member
        if (cur.loading || cur.found != null) return // 防止連點重複查詢
        val input = cur.input
        if (input.length < 3) {
            _state.update { it.copy(member = it.member.copy(message = "請輸入手機號碼或會員編號")) }
            return
        }
        _state.update { it.copy(member = it.member.copy(loading = true, message = "")) }
        memberJob?.cancel()
        memberJob = viewModelScope.launch {
            try {
                when (val r = api().lookupMember(input)) {
                    is LookupResult.Found -> {
                        _state.update {
                            it.copy(member = it.member.copy(loading = false, found = r.member))
                        }
                        // 顯示歡迎詞一下再自動進入問答
                        delay(1800)
                        if (_state.value.screen is Screen.Member) {
                            _state.update { it.copy(screen = Screen.Quiz(0)) }
                        }
                    }
                    is LookupResult.NotFound -> _state.update {
                        it.copy(member = it.member.copy(loading = false, message = r.message))
                    }
                }
            } catch (e: ApiException) {
                _state.update {
                    it.copy(
                        member = it.member.copy(
                            loading = false,
                            message = (e.message ?: "查詢失敗") + if (e.isNetwork) "，可以先略過" else ""
                        )
                    )
                }
            }
        }
    }

    /** 不用會員，直接開始問答 */
    fun memberSkip() {
        memberJob?.cancel()
        _state.update { it.copy(member = MemberUi(), screen = Screen.Quiz(0)) }
    }

    // ================= 問答 =================

    fun selectOption(value: String) {
        val s = _state.value
        val sc = s.screen as? Screen.Quiz ?: return
        val questions = s.config?.questions ?: return
        val q = questions.getOrNull(sc.index) ?: return
        if (s.pendingValue != null) return // 防止連點
        _state.update { it.copy(answers = it.answers + (q.key to value), pendingValue = value) }
        nextJob?.cancel()
        nextJob = viewModelScope.launch {
            delay(NEXT_DELAY_MS)
            _state.update { it.copy(pendingValue = null) }
            if (sc.index + 1 < questions.size) {
                _state.update { it.copy(screen = Screen.Quiz(sc.index + 1)) }
            } else {
                submit()
            }
        }
    }

    fun previousQuestion() {
        val s = _state.value
        val sc = s.screen as? Screen.Quiz ?: return
        nextJob?.cancel()
        _state.update { it.copy(pendingValue = null) }
        if (sc.index > 0) {
            _state.update { it.copy(screen = Screen.Quiz(sc.index - 1)) }
        } else if (s.config?.allowMember == true) {
            _state.update { it.copy(screen = Screen.Member, member = MemberUi()) }
        } else {
            goHome()
        }
    }

    /** 送出答案取得推薦 */
    private fun submit() {
        val s = _state.value
        val answers = s.answers
        val memberNo = s.memberNo
        _state.update { it.copy(screen = Screen.Loading("正在幫你們挑遊戲…")) }
        retryAction = { submit() }
        viewModelScope.launch {
            try {
                val r = api().recommend(answers, memberNo)
                _state.update {
                    it.copy(result = r, screen = Screen.Result, claimMessage = null, claimSuccess = false)
                }
                onUserInteraction()
                if (!memberNo.isNullOrEmpty() && r.logId > 0) claimPoints(r.logId, memberNo)
            } catch (e: ApiException) {
                showError(e.message ?: "連線失敗", e.isAuth, e.isNetwork)
            }
        }
    }

    /** 結果出現後自動幫會員領點數 */
    private fun claimPoints(logId: Int, memberNo: String) {
        claimJob?.cancel()
        claimJob = viewModelScope.launch {
            try {
                val c = api().claim(logId, memberNo)
                val msg = when {
                    c.pointsAdded > 0 -> "+${c.pointsAdded} 點！目前 ${c.totalPoints} 點"
                    c.message.isNotEmpty() -> c.message
                    else -> "點數已登錄"
                }
                _state.update { it.copy(claimMessage = msg, claimSuccess = c.pointsAdded > 0) }
            } catch (e: ApiException) {
                _state.update {
                    it.copy(claimMessage = e.message ?: "點數領取失敗，請洽櫃檯", claimSuccess = false)
                }
            }
        }
    }

    // ================= 影片 =================

    fun openVideo(gameName: String, youtube: YoutubeInfo) {
        _state.update { it.copy(video = VideoUi(gameName, youtube)) }
    }

    fun closeVideo() {
        _state.update { it.copy(video = null) }
        onUserInteraction()
    }

    // ================= 錯誤 =================

    private fun showError(message: String, isAuth: Boolean, isNetwork: Boolean) {
        _state.update { it.copy(screen = Screen.Error(message, isAuth, isNetwork)) }
        onUserInteraction()
    }

    fun retry() {
        val action = retryAction
        if (action != null) action() else goHome()
    }

    // ================= 設定 =================

    fun openSetup(firstRun: Boolean = false) {
        nextJob?.cancel()
        _state.update {
            it.copy(
                screen = Screen.Setup(firstRun),
                setup = SetupUi(url = prefs.serverUrl, key = prefs.deviceKey),
                video = null
            )
        }
    }

    fun setupUrlChanged(v: String) {
        _state.update { it.copy(setup = it.setup.copy(url = v, message = "", success = false)) }
    }

    fun setupKeyChanged(v: String) {
        _state.update { it.copy(setup = it.setup.copy(key = v, message = "", success = false)) }
    }

    fun setupTest() {
        val url = ApiClient.normalizeUrl(_state.value.setup.url)
        val key = _state.value.setup.key.trim()
        if (url.isEmpty() || key.isEmpty()) {
            _state.update { it.copy(setup = it.setup.copy(message = "請輸入伺服器網址與配對碼", success = false)) }
            return
        }
        // HTTP header 只能放 ASCII；中文/全形字元會讓 HttpURLConnection 丟 IllegalArgumentException
        // （原本會被誤報成「網址格式不正確」）
        if (key.any { it.code !in 0x21..0x7E }) {
            _state.update { it.copy(setup = it.setup.copy(message = "配對碼只能包含英文、數字與符號（不可有空白或全形字）", success = false)) }
            return
        }
        _state.update {
            it.copy(setup = it.setup.copy(url = url, testing = true, message = "連線測試中…", success = false))
        }
        viewModelScope.launch {
            try {
                val info = ApiClient(url, key).ping()
                val name = info.storeName.ifEmpty { "（未命名店家）" }
                val ver = if (info.version.isNotEmpty()) "，伺服器版本 ${info.version}" else ""
                val dev = if (info.deviceName.isNotEmpty()) "\n已配對為：${info.deviceName}" else ""
                _state.update {
                    it.copy(
                        setup = it.setup.copy(
                            testing = false,
                            testedUrl = url,
                            testedKey = key,
                            success = true,
                            message = "連線成功！店名：$name$ver$dev"
                        )
                    )
                }
            } catch (e: ApiException) {
                _state.update {
                    it.copy(setup = it.setup.copy(testing = false, success = false, message = e.message ?: "連線失敗"))
                }
            }
        }
    }

    fun setupSave() {
        val s = _state.value.setup
        if (!s.canSave) return
        prefs.serverUrl = s.testedUrl ?: return
        prefs.deviceKey = s.testedKey ?: return
        _state.update { it.copy(config = null) }
        goHome()
        refreshConfigSilently()
    }

    fun setupCancel() {
        if (prefs.isConfigured) goHome()
    }
}
