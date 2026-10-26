"""本機 SQLite 資料庫存取層（Repository）。"""
from __future__ import annotations

import hmac
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from .models import BoardGame, Member, normalize_tags, safe_url

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    name_en TEXT DEFAULT '',
    min_players INTEGER DEFAULT 2,
    max_players INTEGER DEFAULT 4,
    min_time INTEGER DEFAULT 30,
    max_time INTEGER DEFAULT 60,
    weight REAL DEFAULT 2.0,
    min_age INTEGER DEFAULT 8,
    tags TEXT DEFAULT '',
    description TEXT DEFAULT '',
    pos_sku TEXT DEFAULT '',
    price REAL DEFAULT 0,
    stock INTEGER DEFAULT 0,
    rentable INTEGER DEFAULT 1,
    shelf TEXT DEFAULT '',
    youtube_url TEXT DEFAULT '',
    youtube_title TEXT DEFAULT '',
    youtube_is_search INTEGER DEFAULT 0,
    image_url TEXT DEFAULT '',
    active INTEGER DEFAULT 1,
    source TEXT DEFAULT 'manual',
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_games_name ON games(name);
CREATE INDEX IF NOT EXISTS idx_games_sku ON games(pos_sku);

CREATE TABLE IF NOT EXISTS members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_no TEXT UNIQUE NOT NULL,
    name TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    level TEXT DEFAULT '',
    points INTEGER DEFAULT 0,
    source TEXT DEFAULT 'manual',
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_members_phone ON members(phone);

CREATE TABLE IF NOT EXISTS quiz_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT,
    answers TEXT,
    result_ids TEXT,
    member_no TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS member_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_no TEXT NOT NULL,
    pos_sku TEXT NOT NULL DEFAULT '',
    game_id INTEGER,
    kind TEXT NOT NULL DEFAULT 'buy',
    occurred_at TEXT NOT NULL DEFAULT '',
    source TEXT DEFAULT 'import',
    UNIQUE (member_no, pos_sku, kind, occurred_at)
);
CREATE INDEX IF NOT EXISTS idx_history_member ON member_history(member_no);

CREATE TABLE IF NOT EXISTS points_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_no TEXT NOT NULL,
    delta INTEGER NOT NULL,
    reason TEXT DEFAULT '',
    log_id INTEGER,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_ledger_member ON points_ledger(member_no, created_at);

CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    api_key TEXT UNIQUE NOT NULL,
    active INTEGER DEFAULT 1,
    created_at TEXT,
    last_seen TEXT DEFAULT '',
    last_ip TEXT DEFAULT ''
);
"""

# 舊版資料庫缺少的欄位：啟動時自動 ALTER TABLE 補上
MIGRATIONS = {
    "members": [("app_points", "INTEGER DEFAULT 0")],
    "quiz_logs": [("device_id", "INTEGER"), ("claimed", "INTEGER DEFAULT 0"),
                  ("points_awarded", "INTEGER DEFAULT 0")],
}

QUIZ_POINTS_REASON = "作答送點"
HISTORY_KINDS = ("buy", "rent")

GAME_COLUMNS = [
    "name", "name_en", "min_players", "max_players", "min_time", "max_time",
    "weight", "min_age", "tags", "description", "pos_sku", "price", "stock",
    "rentable", "shelf", "youtube_url", "youtube_title", "youtube_is_search",
    "image_url", "active", "source",
]


# 匯入時「沒提供就保留既有值」的欄位
KEEPABLE_FIELDS = ("min_players", "max_players", "min_time", "max_time", "weight", "min_age",
                   "pos_sku", "price", "stock", "rentable", "active")

_GAME_NUM_DEFAULTS = {"min_players": 2, "max_players": 4, "min_time": 30, "max_time": 60,
                      "weight": 2.0, "min_age": 8, "price": 0.0, "stock": 0}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Database:
    """封裝所有 SQLite 操作。每次操作開新連線，適合 Flask 多執行緒。"""

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._lock = threading.RLock()   # 可重入：upsert 內會再呼叫 save
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._db() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)
        try:   # WAL：前台查詢與後台匯入同時進行時比較不會 database is locked
            c = self._connect()
            c.execute("PRAGMA journal_mode=WAL")
            c.close()
        except sqlite3.DatabaseError:
            pass

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        for table, cols in MIGRATIONS.items():
            have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            for col, ddl in cols:
                if col not in have:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
                    if table == "quiz_logs" and col == "claimed":
                        # 舊版已綁會員的紀錄視為已領取，避免升級後被拿來重複領點
                        conn.execute("UPDATE quiz_logs SET claimed=1 WHERE member_no<>'' AND member_no IS NOT NULL")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_member ON quiz_logs(member_no)")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _db(self):
        """開連線 → 交易（成功 commit / 失敗 rollback）→ 一定關閉連線。"""
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @contextmanager
    def _tx(self):
        """寫入交易：BEGIN IMMEDIATE 先拿到寫入鎖，讀到的值在 commit 前不會被別的連線（或別的行程）改掉。"""
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    conn.execute("BEGIN IMMEDIATE")
                    yield conn
            finally:
                conn.close()

    # ---------- 轉換 ----------
    @staticmethod
    def _row_to_game(row: sqlite3.Row) -> BoardGame:
        d = dict(row)
        d.pop("updated_at", None)
        for k, default in _GAME_NUM_DEFAULTS.items():   # 舊資料或 NaN 會存成 NULL
            if d.get(k) is None:
                d[k] = default
        for k in ("name", "name_en", "description", "pos_sku", "shelf", "youtube_url",
                  "youtube_title", "image_url", "source"):
            if d.get(k) is None:
                d[k] = ""
        d["youtube_url"] = safe_url(d["youtube_url"])
        d["image_url"] = safe_url(d["image_url"])
        d["tags"] = normalize_tags(d.get("tags", ""))
        d["rentable"] = bool(d.get("rentable"))
        d["active"] = bool(d.get("active"))
        d["youtube_is_search"] = bool(d.get("youtube_is_search"))
        return BoardGame(**d)

    @staticmethod
    def _game_values(game: BoardGame) -> list:
        d = game.to_dict()
        vals = []
        for c in GAME_COLUMNS:
            v = d[c]
            if isinstance(v, bool):
                v = int(v)
            vals.append(v)
        return vals

    # ---------- 桌遊 ----------
    def list_games(self, keyword: str = "", only_active: bool = False,
                   missing_youtube: bool = False) -> list[BoardGame]:
        sql = "SELECT * FROM games WHERE 1=1"
        params: list = []
        if keyword:
            sql += " AND (name LIKE ? OR name_en LIKE ? OR pos_sku LIKE ? OR tags LIKE ?)"
            kw = f"%{keyword}%"
            params += [kw, kw, kw, kw]
        if only_active:
            sql += " AND active=1"
        if missing_youtube:
            sql += " AND (youtube_url='' OR youtube_url IS NULL OR youtube_is_search=1)"
        sql += " ORDER BY name, id"
        with self._db() as conn:
            return [self._row_to_game(r) for r in conn.execute(sql, params)]

    def get_game(self, game_id: int) -> Optional[BoardGame]:
        with self._db() as conn:
            r = conn.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
        return self._row_to_game(r) if r else None

    def find_game_by_sku_or_name(self, sku: str, name: str) -> Optional[BoardGame]:
        with self._db() as conn:
            r = None
            if sku:
                r = conn.execute("SELECT * FROM games WHERE pos_sku=? ORDER BY id", (sku,)).fetchone()
            if r is None and name:
                # 名稱比對：若兩邊都有商品編號但不同，視為不同商品（避免覆蓋別款的編號）
                if sku:
                    r = conn.execute("SELECT * FROM games WHERE name=? AND (pos_sku='' OR pos_sku IS NULL) "
                                     "ORDER BY id", (name,)).fetchone()
                else:
                    r = conn.execute("SELECT * FROM games WHERE name=? ORDER BY id", (name,)).fetchone()
        return self._row_to_game(r) if r else None

    def save_game(self, game: BoardGame) -> int:
        vals = self._game_values(game.sanitize())
        with self._lock, self._db() as conn:
            if game.id:
                sets = ", ".join(f"{c}=?" for c in GAME_COLUMNS)
                conn.execute(f"UPDATE games SET {sets}, updated_at=? WHERE id=?",
                             vals + [_now(), game.id])
                return game.id
            cols = ", ".join(GAME_COLUMNS)
            qs = ", ".join("?" for _ in GAME_COLUMNS)
            cur = conn.execute(f"INSERT INTO games ({cols}, updated_at) VALUES ({qs}, ?)",
                               vals + [_now()])
            game.id = cur.lastrowid
            return game.id

    def upsert_game(self, incoming: BoardGame, keep_youtube: bool = True,
                    provided: Optional[set] = None) -> str:
        """依 POS 編號或名稱合併。回傳 'inserted' 或 'updated'。

        既有資料的 YouTube 連結、標籤等「店家自己補的資訊」若匯入資料為空就保留。
        provided：匯入資料實際有填的欄位；有給時，沒填的欄位（人數、時間、難度…）沿用既有值，
        不會被預設值蓋掉。
        """
        with self._lock:
            existing = self.find_game_by_sku_or_name(incoming.pos_sku, incoming.name)
            if existing is None:
                self.save_game(incoming)
                return "inserted"
            incoming.id = existing.id
            if provided is not None:
                for attr in KEEPABLE_FIELDS:
                    if attr not in provided:
                        setattr(incoming, attr, getattr(existing, attr))
            return self._merge_and_save(incoming, existing, keep_youtube)

    def _merge_and_save(self, incoming: BoardGame, existing: BoardGame, keep_youtube: bool) -> str:
        incoming.max_players = max(incoming.min_players, incoming.max_players)
        incoming.max_time = max(incoming.min_time, incoming.max_time)
        if keep_youtube and not incoming.youtube_url:
            incoming.youtube_url = existing.youtube_url
            incoming.youtube_title = existing.youtube_title
            incoming.youtube_is_search = existing.youtube_is_search
        elif incoming.youtube_url == existing.youtube_url and not incoming.youtube_title:
            incoming.youtube_title = existing.youtube_title     # 匯出檔沒有標題欄，重匯不要清掉
        for attr in ("tags", "description", "image_url", "name_en", "shelf"):
            if not getattr(incoming, attr):
                setattr(incoming, attr, getattr(existing, attr))
        self.save_game(incoming)
        return "updated"

    def delete_game(self, game_id: int) -> None:
        with self._lock, self._db() as conn:
            conn.execute("DELETE FROM games WHERE id=?", (game_id,))

    def update_youtube(self, game_id: int, url: str, title: str, is_search: bool) -> None:
        with self._lock, self._db() as conn:
            conn.execute(
                "UPDATE games SET youtube_url=?, youtube_title=?, youtube_is_search=?, updated_at=? WHERE id=?",
                (url, title, int(is_search), _now(), game_id))

    def count_games(self) -> dict:
        with self._db() as conn:
            total = conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
            active = conn.execute("SELECT COUNT(*) FROM games WHERE active=1").fetchone()[0]
            yt = conn.execute(
                "SELECT COUNT(*) FROM games WHERE youtube_url<>'' AND youtube_is_search=0").fetchone()[0]
        return {"total": total, "active": active, "with_youtube": yt}

    # ---------- 會員 ----------
    @staticmethod
    def _row_to_member(row: sqlite3.Row) -> Member:
        d = dict(row)
        d.pop("updated_at", None)
        for k in ("name", "phone", "level", "source"):
            if d.get(k) is None:
                d[k] = ""
        d["points"] = d.get("points") or 0
        d["app_points"] = d.get("app_points") or 0
        return Member(**d)

    def upsert_member(self, m: Member, keep: Iterable[str] = ()) -> str:
        """keep：匯入資料沒有這些欄位時，保留既有值（例如檔案沒有手機欄就不清空手機）。"""
        with self._lock, self._db() as conn:
            r = conn.execute("SELECT * FROM members WHERE member_no=?", (m.member_no,)).fetchone()
            if r:
                for k in keep:
                    if r[k] is not None:
                        setattr(m, k, r[k])
                conn.execute(
                    "UPDATE members SET name=?, phone=?, level=?, points=?, source=?, updated_at=? WHERE id=?",
                    (m.name, m.phone, m.level, m.points, m.source, _now(), r["id"]))
                return "updated"
            conn.execute(
                "INSERT INTO members (member_no, name, phone, level, points, source, updated_at) VALUES (?,?,?,?,?,?,?)",
                (m.member_no, m.name, m.phone, m.level, m.points, m.source, _now()))
            return "inserted"

    def list_members(self, keyword: str = "", limit: int = 500) -> list[Member]:
        sql = "SELECT * FROM members"
        params: list = []
        if keyword:
            sql += " WHERE member_no LIKE ? OR name LIKE ? OR phone LIKE ?"
            kw = f"%{keyword}%"
            params = [kw, kw, kw]
        sql += " ORDER BY member_no LIMIT ?"
        params.append(limit)
        with self._db() as conn:
            return [self._row_to_member(r) for r in conn.execute(sql, params)]

    def find_member(self, key: str) -> Optional[Member]:
        """用會員編號或手機號碼查詢。"""
        key = (key or "").strip()
        if not key:
            return None
        with self._db() as conn:
            # 會員編號優先，其次手機
            r = conn.execute("SELECT * FROM members WHERE member_no=? OR phone=? "
                             "ORDER BY (member_no=?) DESC, id", (key, key, key)).fetchone()
        return self._row_to_member(r) if r else None

    def get_member_by_no(self, member_no: str) -> Optional[Member]:
        """只用會員編號精確查詢（後台會員頁用，避免與別人的手機號碼混淆）。"""
        with self._db() as conn:
            r = conn.execute("SELECT * FROM members WHERE member_no=?", (member_no,)).fetchone()
        return self._row_to_member(r) if r else None

    def get_quiz_log(self, log_id: int) -> Optional[dict]:
        with self._db() as conn:
            r = conn.execute("SELECT id, member_no, device_id, claimed, points_awarded FROM quiz_logs "
                             "WHERE id=?", (log_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["member_no"] = d["member_no"] or ""
        d["claimed"] = bool(d["claimed"])
        return d

    def count_members(self) -> int:
        with self._db() as conn:
            return conn.execute("SELECT COUNT(*) FROM members").fetchone()[0]

    # ---------- 問答紀錄 ----------
    def add_quiz_log(self, answers: dict, result_ids: Iterable[int], member_no: str = "",
                     device_id: Optional[int] = None) -> int:
        with self._lock, self._db() as conn:
            cur = conn.execute(
                "INSERT INTO quiz_logs (created_at, answers, result_ids, member_no, device_id, claimed) "
                "VALUES (?,?,?,?,?,0)",
                (_now(), json.dumps(answers, ensure_ascii=False),
                 ",".join(str(i) for i in result_ids), member_no or "", device_id))
            return cur.lastrowid

    def set_log_member(self, log_id: int, member_no: str) -> None:
        with self._lock, self._db() as conn:
            conn.execute("UPDATE quiz_logs SET member_no=? WHERE id=?", (member_no, log_id))

    def list_quiz_logs(self, limit: int = 200, member_no: str = "") -> list[dict]:
        sql = "SELECT * FROM quiz_logs"
        params: list = []
        if member_no:
            sql += " WHERE member_no=?"
            params.append(member_no)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._db() as conn:
            rows = [dict(r) for r in conn.execute(sql, params)]
        for r in rows:
            try:
                ans = json.loads(r["answers"] or "{}")
            except ValueError:
                ans = {}
            r["answers"] = ans if isinstance(ans, dict) else {}
            r["result_ids"] = [int(x) for x in (r["result_ids"] or "").split(",") if x.strip().isdigit()]
            r["created_at"] = r["created_at"] or ""
            r["member_no"] = r["member_no"] or ""
            r["claimed"] = bool(r.get("claimed"))
            r["points_awarded"] = r.get("points_awarded") or 0
        return rows

    def top_recommended(self, limit: int = 10) -> list[tuple[BoardGame, int]]:
        counts: dict[int, int] = {}
        for log in self.list_quiz_logs(limit=5000):
            for gid in log["result_ids"][:3]:
                counts[gid] = counts.get(gid, 0) + 1
        result = []
        for gid, n in sorted(counts.items(), key=lambda x: -x[1])[:limit]:
            g = self.get_game(gid)
            if g:
                result.append((g, n))
        return result

    # ---------- 會員消費／租借紀錄 ----------
    def sku_to_game_ids(self) -> dict[str, int]:
        with self._db() as conn:
            rows = conn.execute("SELECT id, pos_sku FROM games WHERE pos_sku<>'' AND pos_sku IS NOT NULL "
                                "ORDER BY id DESC").fetchall()
        return {r["pos_sku"]: r["id"] for r in rows}     # 同編號多筆時取 id 最小者

    def add_history(self, member_no: str, pos_sku: str, kind: str = "buy", occurred_at: str = "",
                    source: str = "import", game_id: Optional[int] = None) -> bool:
        """新增一筆；已存在（同會員＋商品＋類型＋時間）回傳 False。"""
        if kind not in HISTORY_KINDS:
            raise ValueError(f"kind 必須是 buy 或 rent：{kind!r}")
        with self._lock, self._db() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO member_history (member_no, pos_sku, game_id, kind, occurred_at, source) "
                "VALUES (?,?,?,?,?,?)", (member_no, pos_sku or "", game_id, kind, occurred_at or "", source))
            return cur.rowcount > 0

    def add_history_many(self, rows: list[tuple]) -> int:
        """批次新增 (member_no, pos_sku, kind, occurred_at, source, game_id)，單一交易；回傳實際新增筆數。"""
        for r in rows:
            if r[2] not in HISTORY_KINDS:
                raise ValueError(f"kind 必須是 buy 或 rent：{r[2]!r}")
        if not rows:
            return 0
        with self._tx() as conn:
            before = conn.total_changes
            conn.executemany(
                "INSERT OR IGNORE INTO member_history (member_no, pos_sku, kind, occurred_at, source, game_id) "
                "VALUES (?,?,?,?,?,?)", [(a, b or "", c, d or "", e, f) for a, b, c, d, e, f in rows])
            return conn.total_changes - before

    def history_game_counts(self, member_no: str) -> dict[int, int]:
        """會員紀錄中每款遊戲出現的次數；game_id 沒存時用商品編號即時對應（之後才匯入的桌遊也能對上）。"""
        if not member_no:
            return {}
        # game_id 指向的桌遊被刪掉（例如刪除後重新匯入）時，改用商品編號重新對應
        sql = ("SELECT COALESCE((SELECT g0.id FROM games g0 WHERE g0.id=h.game_id), "
               "(SELECT g.id FROM games g WHERE g.pos_sku=h.pos_sku AND h.pos_sku<>'' "
               "ORDER BY g.id LIMIT 1)) AS gid FROM member_history h WHERE h.member_no=?")
        out: dict[int, int] = {}
        with self._db() as conn:
            for r in conn.execute(sql, (member_no,)):
                if r["gid"] is not None:
                    out[r["gid"]] = out.get(r["gid"], 0) + 1
        return out

    def list_history(self, member_no: str, limit: int = 200) -> list[dict]:
        sql = ("SELECT h.*, COALESCE(g1.name, g2.name, '') AS game_name FROM member_history h "
               "LEFT JOIN games g1 ON g1.id=h.game_id "
               "LEFT JOIN games g2 ON g1.id IS NULL AND h.pos_sku<>'' AND g2.id=("
               "  SELECT id FROM games WHERE pos_sku=h.pos_sku ORDER BY id LIMIT 1) "
               "WHERE h.member_no=? ORDER BY h.occurred_at DESC, h.id DESC LIMIT ?")
        with self._db() as conn:
            return [dict(r) for r in conn.execute(sql, (member_no, limit))]

    def count_history(self) -> int:
        with self._db() as conn:
            return conn.execute("SELECT COUNT(*) FROM member_history").fetchone()[0]

    # ---------- APP 點數 ----------
    def claim_quiz_points(self, log_id: int, member_no: str, points: int, daily_limit: int,
                          device_id: Optional[int] = None) -> tuple[bool, int, int, str]:
        """把問答紀錄綁到會員並依規則加點（同一交易內完成，避免重複領取）。

        device_id 不為 None 時，只能領取該裝置產生的紀錄。
        回傳 (成功綁定, 本次加點, 會員目前點數, 訊息)。
        """
        with self._tx() as conn:
            # 「今天」用伺服器本地時間，與 created_at（_now() 也是本地時間）一致
            today = datetime.now().strftime("%Y-%m-%d")
            log = conn.execute("SELECT id, device_id, claimed FROM quiz_logs WHERE id=?", (log_id,)).fetchone()
            if log is None or (device_id is not None and log["device_id"] != device_id):
                return False, 0, 0, "找不到這次推薦紀錄"
            if log["claimed"]:
                return False, 0, 0, "這次推薦已經登錄過會員了"
            m = conn.execute("SELECT app_points FROM members WHERE member_no=?", (member_no,)).fetchone()
            if m is None:
                return False, 0, 0, "查不到這個會員"
            total = m["app_points"] or 0
            added = 0
            if points <= 0 or daily_limit <= 0:
                msg = "已存到會員紀錄（目前沒有作答送點活動）"
            else:
                used = conn.execute(
                    "SELECT COUNT(*) FROM points_ledger WHERE member_no=? AND reason=? AND log_id IS NOT NULL "
                    "AND substr(created_at,1,10)=?", (member_no, QUIZ_POINTS_REASON, today)).fetchone()[0]
                if used >= daily_limit:
                    msg = f"已存到會員紀錄；今天的作答點數已領過（每日限 {daily_limit} 次）"
                else:
                    added = points
                    total += added
                    conn.execute("INSERT INTO points_ledger (member_no, delta, reason, log_id, created_at) "
                                 "VALUES (?,?,?,?,?)", (member_no, added, QUIZ_POINTS_REASON, log_id, _now()))
                    conn.execute("UPDATE members SET app_points=COALESCE(app_points,0)+? WHERE member_no=?",
                                 (added, member_no))
                    msg = f"已存到會員紀錄，送你 {added} 點！目前共 {total} 點"
            cur = conn.execute("UPDATE quiz_logs SET member_no=?, claimed=1, points_awarded=? "
                               "WHERE id=? AND COALESCE(claimed,0)=0", (member_no, added, log_id))
            if cur.rowcount != 1:          # 理論上不會發生（已持有寫入鎖）；保險起見整筆撤銷
                raise RuntimeError("claim race")
            return True, added, total, msg

    def adjust_points(self, member_no: str, delta: int, reason: str) -> int:
        """後台手動加點（delta>0）或兌換扣點（delta<0）。不可扣成負數。回傳新點數。"""
        reason = (reason or "").strip()[:100]
        if not reason:
            raise ValueError("請填寫原因")
        if delta == 0:
            raise ValueError("點數不可為 0")
        with self._tx() as conn:
            m = conn.execute("SELECT app_points FROM members WHERE member_no=?", (member_no,)).fetchone()
            if m is None:
                raise ValueError("查不到這個會員")
            new = (m["app_points"] or 0) + delta
            if new < 0:
                raise ValueError(f"點數不足：目前 {m['app_points'] or 0} 點，無法扣 {-delta} 點")
            cur = conn.execute("UPDATE members SET app_points=? WHERE member_no=? AND COALESCE(app_points,0)=?",
                               (new, member_no, m["app_points"] or 0))
            if cur.rowcount != 1:
                raise ValueError("點數剛被更新，請重新整理後再試一次")
            conn.execute("INSERT INTO points_ledger (member_no, delta, reason, log_id, created_at) "
                         "VALUES (?,?,?,NULL,?)", (member_no, delta, reason, _now()))
            return new

    def list_points(self, member_no: str, limit: int = 200) -> list[dict]:
        with self._db() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM points_ledger WHERE member_no=? ORDER BY id DESC LIMIT ?", (member_no, limit))]

    # ---------- 平板裝置 ----------
    def add_device(self, name: str, api_key: str) -> int:
        with self._lock, self._db() as conn:
            cur = conn.execute("INSERT INTO devices (name, api_key, active, created_at) VALUES (?,?,1,?)",
                               (name, api_key, _now()))
            return cur.lastrowid

    def list_devices(self) -> list[dict]:
        with self._db() as conn:
            rows = [dict(r) for r in conn.execute("SELECT * FROM devices ORDER BY id")]
        for r in rows:
            r["active"] = bool(r["active"])
            r["last_seen"] = r["last_seen"] or ""
            r["last_ip"] = r["last_ip"] or ""
        return rows

    def get_device_by_key(self, api_key: str) -> Optional[dict]:
        if not api_key:
            return None
        # 不用 WHERE api_key=? 直接比對：逐一以 hmac.compare_digest 比較（固定時間），平板數量很少
        with self._db() as conn:
            rows = conn.execute("SELECT * FROM devices WHERE active=1").fetchall()
        given = api_key.encode("utf-8", "replace")
        found = None
        for r in rows:
            if hmac.compare_digest(str(r["api_key"] or "").encode("utf-8", "replace"), given) and found is None:
                found = dict(r)
        return found

    def touch_device(self, device_id: int, ip: str = "") -> None:
        with self._lock, self._db() as conn:
            conn.execute("UPDATE devices SET last_seen=?, last_ip=? WHERE id=?", (_now(), ip[:64], device_id))

    def set_device_active(self, device_id: int, active: bool) -> None:
        with self._lock, self._db() as conn:
            conn.execute("UPDATE devices SET active=? WHERE id=?", (int(active), device_id))

    def delete_device(self, device_id: int) -> None:
        with self._lock, self._db() as conn:
            conn.execute("DELETE FROM devices WHERE id=?", (device_id,))

    def count_devices(self) -> dict:
        with self._db() as conn:
            total = conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
            active = conn.execute("SELECT COUNT(*) FROM devices WHERE active=1").fetchone()[0]
        return {"total": total, "active": active}

    # ---------- 設定 ----------
    def get_setting(self, key: str, default=None):
        with self._db() as conn:
            r = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if r is None:
            return default
        try:
            return json.loads(r["value"])
        except (TypeError, ValueError):
            return r["value"]

    def set_setting(self, key: str, value) -> None:
        with self._lock, self._db() as conn:
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                         (key, json.dumps(value, ensure_ascii=False)))
