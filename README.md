# 🎲 桌遊推薦 APP（第 2 版）

客人在店內 **Android 平板** 回答 **5 個小選擇題**（可先輸入會員），系統從店裡的桌遊資料庫挑出最適合的幾款，並附上 **YouTube 教學影片**。
櫃檯 Windows 電腦執行本伺服器：後台、POS 連線、會員與點數、YouTube、資料庫都在這台。多台平板共用同一台伺服器。
原本的網頁前台保留作為備用（平板沒裝 APP 時，用瀏覽器開也能用）。

```
 [Android 平板 ×N] ──Wi-Fi──▶ [櫃檯 Windows：本伺服器 + SQLite] ──唯讀──▶ [POS 資料庫]
   （X-Device-Key）              後台 /admin、網頁備用前台 /
```

## 快速開始（Windows）

1. 安裝 Python 3.10 以上（安裝時勾選 **Add Python to PATH**）
2. 解壓縮後雙擊 **`start.bat`**（第一次會自動安裝套件，約 1 分鐘）
3. 視窗會顯示網址：
   - 前台（客人作答）：`http://你的電腦IP:5000/`
   - 後台（店員管理）：`http://你的電腦IP:5000/admin`
4. 預設後台密碼 **`admin1234`**，登入後請到「設定」修改

> 平板 APP 設定方式見下方「Android 平板配對」。沒有 APP 時，平板瀏覽器開前台網址也能用。第一次啟動若 Windows 防火牆詢問，請允許「私人網路」。
> 第一次啟動會自動匯入 40 款範例桌遊，可以在後台刪除或用自己的資料覆蓋。

## 功能

| 區塊 | 功能 |
|---|---|
| Android 平板前台 | 透過 JSON API 連線本伺服器；開始 → 會員（可略過）→ 5 題 → 結果 |
| 網頁前台（備用） | 同樣流程：開始 → 會員（可略過）→ 5 題（人數／時間／🐶🦊🐝🦉🐣／宵夜／贏的台詞）→ 結果；閒置自動回首頁 |
| 推薦結果 | 契合度、自然中文推薦理由、人數時間難度、櫃位、YouTube 教學影片；會員會避開玩過的遊戲並參考常玩風格 |
| 題目設定 | 後台可編輯題目、選項文字、emoji、標籤權重、難度目標；嚴格檢查格式、可一鍵還原預設 |
| 平板配對 | 每台平板一組裝置金鑰，可停用／刪除，顯示最後連線時間 |
| 會員點數 | 作答送點（本系統自己記點，不寫入 POS），每日上限、兌換扣點、手動加點、點數明細 |
| 找桌遊 | 客人可依名稱或類型瀏覽全部桌遊 |
| 桌遊資料庫 | 新增／編輯／刪除、上下架、類型標籤、難度、櫃位、庫存 |
| YouTube 教學 | 單款或批次自動搜尋教學影片；也可手動貼網址 |
| 匯入／匯出 | CSV（UTF-8 / Big5）、Excel；中文欄名自動辨識；匯出可用 Excel 編修後再匯入 |
| POS 連線 | 唯讀連線 MySQL / SQL Server / PostgreSQL / SQLite，同步桌遊商品、會員、**銷售／租借紀錄**，欄位可自訂對應 |
| 會員 | 會員列表（手機遮罩、APP 點數）、每位會員的推薦紀錄、點數明細、銷售／租借紀錄 |
| 問答紀錄 | 每次作答與推薦結果、最常被推薦的桌遊排行 |

## 推薦怎麼算

| 題目 | 選項 → 影響 | 配分 |
|---|---|---|
| 1. 幾個人？ | 硬條件：不支援的遊戲直接排除（全被排除時放寬取最接近）；選 2 人時兩人專屬遊戲加分 | — |
| 2. 想玩多久？ | 遊戲時長落在區間內滿分，越遠分越低 | 25 |
| 3. 你們最像？ | 🐶熱情狗狗（派對、文字、反應）／🦊狡猾狐狸（吹牛、推理）／🐝團結蜜蜂（合作、冒險）／🦉聰明貓頭鷹（策略、經濟、抽象）／🐣雞媽媽（家庭、輕鬆、反應；避開 12+、吹牛扣分） | 30 |
| 4. 今晚宵夜？ | 換算難度：🍜泡麵≈1.3／🍢鹹酥雞≈2.1／🍲麻辣鍋≈3.2（不限重度）／🍰甜點≈1.8；偏好標籤小加分 | 25 |
| 5. 贏的時候想聽？ | 「笑死我了！」派對文字／「原來你就是兇手！」推理吹牛／「多虧有你才過關！」合作／「這步我想了三回合」策略抽象雙人／「看我大翻盤！」冒險卡牌反應 | 15 |
| 店內可玩／有庫存 | | 5 |
| 會員個人化 | 和會員常玩遊戲的標籤分布、平均難度相近 → 最多 +10，理由例如「和你常玩的《卡坦島》風格相近」 | +10 |

- 標籤命中選項中權重最高的那個得分（主要標籤 1.0、次要 0.6~0.8）。
- 會員買過／租過的遊戲先排除；排除後不足推薦款數，才用玩過的補，理由標示「你玩過，值得再開一局」。
- 所以 **類型標籤、難度、人數、時間、商品編號** 這幾項資料填得越準，推薦越準。

## 題目設定

後台「❓ 題目設定」可以直接編輯題目 JSON（預設檔在 `core/quiz_default.json`）：

- `type`：`players`（人數，必須剛好一題）、`time`（時間）、`tags`（依標籤計分）、`difficulty`（依難度計分）
- `weight`：這題配分；`options[].tags`：`{"標籤": 0~1}`；`penalty_tags`：扣分標籤；`kid: true`：避開 `kid_age` 歲以上遊戲
- `target` / `max_weight`：宵夜題的目標難度與上限（`null` 表示不限）
- `reason`：推薦理由，可用 `{time_text}`、`{weight_text}`
- 儲存前會嚴格檢查（不認得的標籤、重複代碼、數值範圍…），有錯不會存；按「還原預設」回到原始題目
- ⚠️ 選項的 `value` 是平板 APP 傳回來的代碼，上線後請盡量不要改；改題目後平板重新載入（回到首頁）就會套用

## Android 平板配對

1. 櫃檯電腦啟動本程式（`start.bat`），平板與電腦連同一個 Wi-Fi
2. 後台「📱 平板配對」→ 輸入裝置名稱（例如「櫃檯平板 1」）→ 按「產生金鑰」
3. 頁面會大字顯示 **伺服器網址**（`http://區網IP:5000`）與 **裝置金鑰**，輸入到平板 APP 的設定畫面
4. 平板遺失或不用了：按「停用」或「刪除」，該金鑰立即失效

- 若平板連不上：確認 Windows 防火牆允許 Python「私人網路」、電腦 IP 沒變（建議在路由器設定固定 IP）
- APP 安裝與編譯說明：[android/README_android.md](android/README_android.md)

### 平板 API（給 APP 開發者）

所有請求都要帶 header `X-Device-Key: <裝置金鑰>`；金鑰無效回 `401 {"ok":false,"error":"..."}`。錯誤一律回 JSON（含 `ok:false`、`error`、`message`）。

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/api/v1/ping` | `{"ok":true,"store_name","version":"2.0","device_name"}` |
| GET | `/api/v1/config` | 店名、`top_n`、`allow_member`、`points_per_quiz`、`show_price`、`questions[]` |
| POST | `/api/v1/member/lookup` | `{"member_key"}`（手機或會員編號）→ `{"ok":true,"member_no","greeting","points"}`；查無 `{"ok":false,"message"}`；會員功能關閉 403；查太頻繁 429 |
| POST | `/api/v1/recommend` | `{"answers":{...},"member_no":可選}` → `{"ok":true,"log_id","results":[...],"member":null 或 {...}}`；答案不合法 400 |
| POST | `/api/v1/quiz/<log_id>/claim` | `{"member_no"}` → `{"ok":true,"message","points_added","total_points"}`；只能 claim 同一平板產生、尚未 claim 的紀錄 |

## 會員點數

- 本系統自己記點（`APP 點數`），**不寫入 POS**；POS 同步來的點數另外顯示為「POS 點數」
- 後台「⚙️ 設定」：每次作答送幾點（預設 10）、每位會員每天最多領幾次（預設 1）；任一設 0 表示不送點
- 平板：作答後輸入會員並 claim 才送點；網頁前台：作答前輸入會員，看結果時自動送點
- 超過每日上限仍會把推薦存到會員紀錄，只是不加點
- 後台會員明細：點數明細、**兌換扣點**（需填兌換內容，不可扣成負數）、**手動加點**（需填原因）

## YouTube 教學影片

- **有 API 金鑰（建議）**：到 Google Cloud Console 建立專案 → 啟用「YouTube Data API v3」→ 建立 API 金鑰 → 貼到後台「YouTube 教學」。系統用「遊戲名 桌遊 教學」搜尋，優先挑標題有「教學／規則／how to play」的影片，避開開箱與實況。免費額度一天約可搜尋 100 款。
- **沒有金鑰**：會存 YouTube 搜尋頁連結，客人點了會看到搜尋結果。之後補上金鑰再按一次批次搜尋即可升級成單一影片。
- 搜尋到的影片不一定完美，建議店員抽查，不滿意就在編輯頁手動貼網址。

## POS 連線設定

1. 先安裝對應的驅動（在專案資料夾開命令列）：
   ```
   .venv\Scripts\pip install pymysql          # MySQL / MariaDB
   .venv\Scripts\pip install pyodbc           # SQL Server
   .venv\Scripts\pip install psycopg2-binary  # PostgreSQL
   ```
2. 後台「POS 連線」填連線字串，例如 `mysql+pymysql://reader:密碼@192.168.1.10:3306/pos`
3. 填「查詢語法」，例如：
   ```sql
   SELECT item_no, item_name, sale_price, qty FROM products WHERE category_id = 12
   ```
4. 按「預覽桌遊資料」確認欄位 → 在「欄位對應」填 POS 欄名（例如 遊戲名稱=item_name、商品編號=item_no）
5. 按「立即同步」

### 銷售／租借紀錄同步（排除會員玩過的遊戲）

1. 「POS 連線」頁下方勾選「同步銷售／租借紀錄」，填查詢語法，例如：
   ```sql
   SELECT card_no, item_no, sale_type, sale_date FROM sales_detail WHERE card_no <> '' AND sale_date >= '2025-01-01'
   ```
2. 欄位對應：會員編號、商品編號、類型（購買／租借，可無）、交易時間；沒有類型欄時選「視為購買／租借」
3. 依「商品編號」對應到桌遊資料庫（請確認桌遊的商品編號與 POS 一致）；同一筆重複同步不會重複
4. 沒有 POS 連線也可以：「匯入／匯出」頁上傳 CSV / Excel（欄位：會員編號、商品編號、類型、日期），有範本可下載

說明：
- 只允許 SELECT，不會改到 POS 的資料；建議在 POS 建立唯讀帳號
- 依「商品編號」比對更新；POS 沒有的資料（標籤、難度、教學影片、介紹）在本系統補，同步時不會被清掉
- POS 通常沒有人數、時間、難度，同步後請到後台補上，或匯出 CSV 用 Excel 批次填好再匯入

## 資料存放

- 所有資料在 `data/boardgames.db`（SQLite），**備份這一個檔案即可**
- 從第 1 版升級：直接覆蓋程式檔，保留 `data/` 資料夾；啟動時會自動補上新欄位與新資料表
- POS 連線密碼、YouTube 金鑰、平板裝置金鑰也存在這個檔案裡，請勿外流

## 專案結構

```
boardgame_recommender/
├─ app.py                  Flask 主程式（前台＋後台路由）
├─ start.bat               Windows 一鍵啟動
├─ core/
│  ├─ models.py            BoardGame / Member 資料模型、類型標籤
│  ├─ database.py          SQLite 存取層（含舊資料庫自動升級、點數、裝置）
│  ├─ quiz.py              題目設定讀取與嚴格驗證
│  ├─ quiz_default.json    預設題目（後台可改）
│  ├─ recommender.py       資料驅動推薦計分、會員排除與個人化
│  ├─ importer.py          CSV / Excel 匯入匯出（桌遊、會員、銷售紀錄）
│  ├─ pos_connector.py     POS 唯讀連線與同步
│  └─ youtube_finder.py    YouTube 教學影片搜尋
├─ templates/              前台與後台頁面
├─ static/style.css
├─ sample_data/games_sample.csv  範例桌遊 40 款
├─ android/                Android 平板 APP（見 android/README_android.md）
└─ tests/                  自動測試（python -m pytest tests）
```

## 其他

- 換 Port：設定環境變數 `BGR_PORT=8080` 再啟動
- 資料庫位置：環境變數 `BGR_DATA_DIR`
- 只在店內區網使用；若要放到網路上，請另外加 HTTPS 與更嚴格的帳號管理
