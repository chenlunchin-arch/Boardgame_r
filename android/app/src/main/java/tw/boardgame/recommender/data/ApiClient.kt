package tw.boardgame.recommender.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.io.BufferedReader
import java.io.IOException
import java.io.InputStream
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.MalformedURLException
import java.net.SocketTimeoutException
import java.net.URL

/** 會員查詢的兩種結果：找到 / 找不到（帶伺服器訊息） */
sealed class LookupResult {
    data class Found(val member: MemberInfo) : LookupResult()
    data class NotFound(val message: String) : LookupResult()
}

/**
 * 與櫃檯伺服器溝通。只用 HttpURLConnection + org.json，所有呼叫都在 Dispatchers.IO 執行。
 * @param baseUrl 例：http://192.168.1.10:5000（不含結尾斜線）
 * @param deviceKey 後台「平板配對」產生的配對碼
 */
class ApiClient(
    private val baseUrl: String,
    private val deviceKey: String
) {

    companion object {
        private const val CONNECT_TIMEOUT_MS = 5000
        private const val READ_TIMEOUT_MS = 15000

        /** 整理使用者輸入的網址：補 http://、去掉結尾斜線與空白 */
        fun normalizeUrl(input: String): String {
            var s = input.trim()
            if (s.isEmpty()) return s
            if (!s.startsWith("http://", ignoreCase = true) &&
                !s.startsWith("https://", ignoreCase = true)
            ) {
                s = "http://$s"
            }
            while (s.endsWith("/")) s = s.dropLast(1)
            return s
        }
    }

    // ---------- 公開 API ----------

    suspend fun ping(): PingInfo {
        val json = request("GET", "/api/v1/ping", null)
        return PingInfo(
            storeName = json.str("store_name"),
            version = json.str("version"),
            deviceName = json.str("device_name")
        )
    }

    suspend fun getConfig(): AppConfig {
        val json = request("GET", "/api/v1/config", null)
        return parseConfig(json)
    }

    suspend fun lookupMember(memberKey: String): LookupResult {
        val body = JSONObject().put("member_key", memberKey)
        val json = request("POST", "/api/v1/member/lookup", body, allowNotOk = true)
        if (!json.optBoolean("ok", false)) {
            return LookupResult.NotFound(json.errorText("查無此會員"))
        }
        val memberNo = json.str("member_no")
        if (memberNo.isEmpty()) return LookupResult.NotFound(json.errorText("查無此會員"))
        return LookupResult.Found(
            MemberInfo(
                memberNo = memberNo,
                greeting = json.str("greeting"),
                points = json.optInt("points", 0)
            )
        )
    }

    suspend fun recommend(answers: Map<String, String>, memberNo: String?): RecommendResult {
        val ans = JSONObject()
        for ((k, v) in answers) ans.put(k, v)
        val body = JSONObject().put("answers", ans)
        if (!memberNo.isNullOrEmpty()) body.put("member_no", memberNo)
        val json = request("POST", "/api/v1/recommend", body)
        return parseRecommend(json)
    }

    suspend fun claim(logId: Int, memberNo: String): ClaimResult {
        val body = JSONObject().put("member_no", memberNo)
        val json = request("POST", "/api/v1/quiz/$logId/claim", body)
        return ClaimResult(
            message = json.str("message"),
            pointsAdded = json.optInt("points_added", 0),
            totalPoints = json.optInt("total_points", 0)
        )
    }

    // ---------- 底層 HTTP ----------

    /**
     * 送出請求並回傳 JSON。
     * allowNotOk = true 時，HTTP 200 但 ok=false 不丟例外（給會員查詢用）。
     */
    private suspend fun request(
        method: String,
        path: String,
        body: JSONObject?,
        allowNotOk: Boolean = false
    ): JSONObject = withContext(Dispatchers.IO) {
        if (baseUrl.isBlank()) throw ApiException("尚未設定伺服器網址")
        var conn: HttpURLConnection? = null
        try {
            conn = (URL(baseUrl + path).openConnection() as HttpURLConnection).apply {
                requestMethod = method
                connectTimeout = CONNECT_TIMEOUT_MS
                readTimeout = READ_TIMEOUT_MS
                useCaches = false
                setRequestProperty("Accept", "application/json")
                setRequestProperty("X-Device-Key", deviceKey)
                if (body != null) {
                    doOutput = true
                    setRequestProperty("Content-Type", "application/json; charset=utf-8")
                }
            }
            if (body != null) {
                OutputStreamWriter(conn.outputStream, Charsets.UTF_8).use { it.write(body.toString()) }
            }

            val code = conn.responseCode
            // 錯誤狀態碼的內容在 errorStream（也是 JSON），讀不到就當空字串
            val stream: InputStream? = if (code in 200..299) conn.inputStream else conn.errorStream
            val text = try {
                stream?.let { readAll(it) } ?: ""
            } catch (e: IOException) {
                ""
            }
            val json = try {
                if (text.isBlank()) JSONObject() else JSONObject(text)
            } catch (e: JSONException) {
                null
            }

            if (code == 401) {
                val msg = json?.errorText("").orEmpty()
                throw ApiException(
                    if (msg.isNotEmpty()) "配對碼錯誤：$msg" else "平板配對碼錯誤，請到設定頁重新輸入",
                    isAuth = true
                )
            }
            if (json == null) {
                throw ApiException("伺服器回應格式不正確（HTTP $code）", httpCode = code)
            }
            if (code !in 200..299) {
                // 會員查詢找不到時，伺服器可能用 404 + ok:false 回應
                // 429 太頻繁、409 重複領取、404 不存在、403 功能關閉、405 方法錯誤…都讀 message 顯示
                if (allowNotOk && json.has("ok")) return@withContext json
                throw ApiException(json.errorText(httpErrorText(code)), httpCode = code)
            }
            if (!allowNotOk && json.has("ok") && !json.optBoolean("ok", true)) {
                throw ApiException(json.errorText("伺服器回應失敗"))
            }
            json
        } catch (e: ApiException) {
            throw e
        } catch (e: MalformedURLException) {
            throw ApiException("伺服器網址格式不正確")
        } catch (e: SocketTimeoutException) {
            throw ApiException("連線逾時，伺服器沒有回應", isNetwork = true)
        } catch (e: IOException) {
            throw ApiException("連不到伺服器（${e.javaClass.simpleName}）", isNetwork = true)
        } catch (e: IllegalArgumentException) {
            throw ApiException("伺服器網址格式不正確")
        } catch (e: ClassCastException) {
            throw ApiException("伺服器網址格式不正確")
        } finally {
            conn?.disconnect()
        }
    }

    /** 伺服器沒給 message 時的預設中文說明 */
    private fun httpErrorText(code: Int): String = when (code) {
        403 -> "此功能目前未開放"
        404 -> "找不到資料"
        405 -> "請求方式錯誤，請更新 APP 或伺服器"
        409 -> "這次已經領過點數了"
        429 -> "操作太頻繁，請稍候一分鐘再試"
        in 500..599 -> "伺服器發生錯誤（HTTP $code）"
        else -> "伺服器錯誤（HTTP $code）"
    }

    private fun readAll(stream: InputStream): String =
        BufferedReader(InputStreamReader(stream, Charsets.UTF_8)).use { it.readText() }

    // ---------- JSON 解析 ----------

    private fun parseConfig(json: JSONObject): AppConfig {
        val questions = mutableListOf<QuizQuestion>()
        val qArr = json.optJSONArray("questions") ?: JSONArray()
        for (i in 0 until qArr.length()) {
            val q = qArr.optJSONObject(i) ?: continue
            val options = mutableListOf<QuizOption>()
            val oArr = q.optJSONArray("options") ?: JSONArray()
            for (j in 0 until oArr.length()) {
                val o = oArr.optJSONObject(j) ?: continue
                val value = o.str("value")
                if (value.isEmpty()) continue
                options.add(
                    QuizOption(
                        value = value,
                        label = o.str("label").ifEmpty { value },
                        emoji = o.str("emoji")
                    )
                )
            }
            val key = q.str("key")
            if (key.isEmpty() || options.isEmpty()) continue
            questions.add(
                QuizQuestion(
                    key = key,
                    title = q.str("title").ifEmpty { "第 ${i + 1} 題" },
                    subtitle = q.str("subtitle"),
                    options = options
                )
            )
        }
        return AppConfig(
            storeName = json.str("store_name"),
            topN = json.optInt("top_n", 3),
            allowMember = json.optBoolean("allow_member", false),
            pointsPerQuiz = json.optInt("points_per_quiz", 0),
            showPrice = json.optBoolean("show_price", false),
            questions = questions
        )
    }

    private fun parseRecommend(json: JSONObject): RecommendResult {
        val list = mutableListOf<GameResult>()
        val arr = json.optJSONArray("results") ?: JSONArray()
        for (i in 0 until arr.length()) {
            val g = arr.optJSONObject(i) ?: continue
            list.add(parseGame(g))
        }
        val member = if (json.has("member") && !json.isNull("member")) {
            json.optJSONObject("member")?.let { m ->
                MemberRecommendInfo(
                    greeting = m.str("greeting"),
                    excludedCount = m.optInt("excluded_count", 0),
                    personalized = m.optBoolean("personalized", false)
                )
            }
        } else null
        return RecommendResult(
            logId = json.optInt("log_id", 0),
            results = list,
            member = member
        )
    }

    private fun parseGame(g: JSONObject): GameResult {
        val youtube = if (g.has("youtube") && !g.isNull("youtube")) {
            g.optJSONObject("youtube")?.let { y ->
                val vid = y.str("video_id").ifEmpty { null }
                YoutubeInfo(
                    url = y.str("url"),
                    videoId = vid,
                    isSearch = y.optBoolean("is_search", vid == null),
                    title = y.str("title")
                )
            }
        } else null
        val price = if (g.isNull("price")) 0.0 else g.optDouble("price", 0.0).let { if (it.isNaN()) 0.0 else it }
        return GameResult(
            id = g.str("id"),
            name = g.str("name"),
            nameEn = g.str("name_en"),
            playersText = g.str("players_text"),
            timeText = g.str("time_text"),
            weightText = g.str("weight_text"),
            minAge = g.optInt("min_age", 0),
            shelf = g.str("shelf"),
            price = price,
            inStock = g.optBoolean("in_stock", true),
            tags = g.strList("tags"),
            description = g.str("description"),
            imageUrl = g.str("image_url"),
            matchPercent = g.optInt("match_percent", 0),
            reasons = g.strList("reasons"),
            playedBefore = g.optBoolean("played_before", false),
            youtube = youtube
        )
    }
}

// ---------- JSON 小工具（容錯：null / 缺欄位都回空字串） ----------

/** 安全取字串：缺欄位或 null 都回 ""（避免 optString 把 null 變成 "null"） */
internal fun JSONObject.str(key: String): String =
    if (!has(key) || isNull(key)) "" else optString(key, "").trim()

/** 安全取字串陣列 */
internal fun JSONObject.strList(key: String): List<String> {
    if (!has(key) || isNull(key)) return emptyList()
    val arr = optJSONArray(key) ?: return emptyList()
    val out = mutableListOf<String>()
    for (i in 0 until arr.length()) {
        if (arr.isNull(i)) continue
        val s = arr.optString(i, "").trim()
        if (s.isNotEmpty()) out.add(s)
    }
    return out
}

/** 取錯誤訊息：優先 message，其次 error，都沒有就用預設 */
internal fun JSONObject.errorText(default: String): String {
    val m = str("message")
    if (m.isNotEmpty()) return m
    val e = str("error")
    if (e.isNotEmpty()) return e
    return default
}
