package tw.boardgame.recommender.data

// ===== 伺服器回傳資料的 Kotlin 版本（全部欄位都有預設值，缺欄位也不會當機） =====

/** ping 結果 */
data class PingInfo(
    val storeName: String = "",
    val version: String = "",
    /** 這台平板在後台配對時的名稱 */
    val deviceName: String = ""
)

/** 題目選項 */
data class QuizOption(
    val value: String,
    val label: String,
    val emoji: String = ""
)

/** 一道題目 */
data class QuizQuestion(
    val key: String,
    val title: String,
    val subtitle: String = "",
    val options: List<QuizOption> = emptyList()
)

/** 店家設定（題目也在裡面） */
data class AppConfig(
    val storeName: String = "",
    val topN: Int = 3,
    val allowMember: Boolean = false,
    val pointsPerQuiz: Int = 0,
    val showPrice: Boolean = false,
    val questions: List<QuizQuestion> = emptyList()
)

/** 會員查詢結果 */
data class MemberInfo(
    val memberNo: String,
    val greeting: String = "",
    val points: Int = 0
)

/** YouTube 教學影片資訊 */
data class YoutubeInfo(
    val url: String = "",
    val videoId: String? = null,
    val isSearch: Boolean = true,
    val title: String = ""
)

/** 一款推薦的桌遊 */
data class GameResult(
    val id: String = "",
    val name: String = "",
    val nameEn: String = "",
    val playersText: String = "",
    val timeText: String = "",
    val weightText: String = "",
    val minAge: Int = 0,
    val shelf: String = "",
    val price: Double = 0.0,
    val inStock: Boolean = true,
    val tags: List<String> = emptyList(),
    val description: String = "",
    val imageUrl: String = "",
    val matchPercent: Int = 0,
    val reasons: List<String> = emptyList(),
    val playedBefore: Boolean = false,
    val youtube: YoutubeInfo? = null
)

/** 推薦結果中與會員相關的資訊 */
data class MemberRecommendInfo(
    val greeting: String = "",
    val excludedCount: Int = 0,
    val personalized: Boolean = false
)

/** 推薦整體結果 */
data class RecommendResult(
    val logId: Int = 0,
    val results: List<GameResult> = emptyList(),
    val member: MemberRecommendInfo? = null
)

/** 領點數結果 */
data class ClaimResult(
    val message: String = "",
    val pointsAdded: Int = 0,
    val totalPoints: Int = 0
)

/** 網路呼叫失敗時丟出的例外；isAuth = 配對碼錯誤（401） */
class ApiException(
    message: String,
    val isAuth: Boolean = false,
    val isNetwork: Boolean = false,
    /** HTTP 狀態碼（0 = 沒有收到回應） */
    val httpCode: Int = 0
) : Exception(message)
