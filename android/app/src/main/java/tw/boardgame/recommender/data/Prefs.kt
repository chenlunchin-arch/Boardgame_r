package tw.boardgame.recommender.data

import android.content.Context
import android.content.SharedPreferences

/** 平板本機設定：伺服器網址、配對碼、上次的店名（SharedPreferences） */
class Prefs(context: Context) {

    private val sp: SharedPreferences =
        context.applicationContext.getSharedPreferences("bg_prefs", Context.MODE_PRIVATE)

    var serverUrl: String
        get() = sp.getString(KEY_URL, "") ?: ""
        set(value) = sp.edit().putString(KEY_URL, value).apply()

    var deviceKey: String
        get() = sp.getString(KEY_DEVICE, "") ?: ""
        set(value) = sp.edit().putString(KEY_DEVICE, value).apply()

    var lastStoreName: String
        get() = sp.getString(KEY_STORE, "") ?: ""
        set(value) = sp.edit().putString(KEY_STORE, value).apply()

    /** 網址與配對碼都填了才算設定完成 */
    val isConfigured: Boolean
        get() = serverUrl.isNotBlank() && deviceKey.isNotBlank()

    companion object {
        private const val KEY_URL = "server_url"
        private const val KEY_DEVICE = "device_key"
        private const val KEY_STORE = "store_name"
    }
}
