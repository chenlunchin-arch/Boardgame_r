package tw.boardgame.recommender.ui.screens

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.LruCache
import androidx.compose.foundation.Image
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.URL

/** 極簡圖片載入（不引入第三方套件）：記憶體快取＋縮小取樣 */
private object ImageCache {
    val cache = object : LruCache<String, Bitmap>(24 * 1024 * 1024) {
        override fun sizeOf(key: String, value: Bitmap): Int = value.byteCount
    }

    suspend fun load(url: String): Bitmap? = withContext(Dispatchers.IO) {
        val cached: Bitmap? = cache.get(url)
        if (cached != null) return@withContext cached
        var conn: HttpURLConnection? = null
        try {
            conn = (URL(url).openConnection() as HttpURLConnection).apply {
                connectTimeout = 5000
                readTimeout = 10000
            }
            if (conn.responseCode !in 200..299) return@withContext null
            val bytes = conn.inputStream.use { it.readBytes() }
            // 先量尺寸，再縮小到寬約 600px，避免大圖吃光記憶體
            val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
            var sample = 1
            while (bounds.outWidth / (sample * 2) >= 600) sample *= 2
            val opts = BitmapFactory.Options().apply { inSampleSize = sample }
            val bmp = BitmapFactory.decodeByteArray(bytes, 0, bytes.size, opts)
            if (bmp != null) cache.put(url, bmp)
            bmp
        } catch (e: Exception) {
            null
        } finally {
            conn?.disconnect()
        }
    }
}

/** 把相對路徑（/static/xx.jpg）補成完整網址 */
fun resolveImageUrl(baseUrl: String, imageUrl: String): String {
    if (imageUrl.isBlank()) return ""
    if (imageUrl.startsWith("http://", true) || imageUrl.startsWith("https://", true)) return imageUrl
    if (imageUrl.startsWith("//")) return "http:$imageUrl"
    if (baseUrl.isBlank()) return ""
    return if (imageUrl.startsWith("/")) baseUrl + imageUrl else "$baseUrl/$imageUrl"
}

/** 顯示網路圖片；載入失敗或沒網址時什麼都不畫（呼叫端可放底色） */
@Composable
fun RemoteImage(
    url: String,
    contentDescription: String?,
    modifier: Modifier = Modifier,
    contentScale: ContentScale = ContentScale.Crop
) {
    val bitmap by produceState<Bitmap?>(initialValue = null, key1 = url) {
        value = if (url.isBlank()) null else ImageCache.load(url)
    }
    val bmp = bitmap
    if (bmp != null) {
        Image(
            bitmap = bmp.asImageBitmap(),
            contentDescription = contentDescription,
            modifier = modifier,
            contentScale = contentScale
        )
    }
}
