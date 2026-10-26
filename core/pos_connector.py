"""POS 資料庫連接器（唯讀）。

透過 SQLAlchemy 連線字串，支援：
  - MySQL / MariaDB   mysql+pymysql://帳號:密碼@主機:3306/資料庫
  - SQL Server        mssql+pyodbc://帳號:密碼@主機/資料庫?driver=ODBC+Driver+17+for+SQL+Server
  - PostgreSQL        postgresql+psycopg2://帳號:密碼@主機:5432/資料庫
  - SQLite（測試用）  sqlite:///C:/POS/pos.db

本程式只執行 SELECT 查詢，不會寫入 POS 資料庫。
欄位對應：{本系統欄位: POS 欄位}；沒填的欄位會用中英文別名自動猜測。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

from .database import Database
from .importer import GameImporter, HistoryImporter, MemberImporter, ImportResult

DEFAULT_GAME_QUERY = "SELECT * FROM products WHERE category = '桌遊'"
DEFAULT_MEMBER_QUERY = "SELECT * FROM members"
DEFAULT_HISTORY_QUERY = "SELECT member_no, item_no, sale_type, sale_date FROM sales WHERE member_no <> ''"

# 注意：刻意對「原始字串」（含字串常值與註解內容）比對，寧可誤擋也不讓註解／引號技巧繞過。
# replace 不列入：REPLACE() 是常用字串函式，而 REPLACE 陳述式無法出現在 SELECT/WITH 開頭的查詢中。
# into 擋 SELECT ... INTO 新資料表 / INTO OUTFILE。真正的防線仍是 POS 端的「唯讀帳號」。
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|merge|upsert|exec|execute|grant|revoke"
    r"|into|xp_cmdshell|dbms_\w+|pg_terminate_backend|pg_cancel_backend|set_config|openrowset|opendatasource|load_file|lo_import|lo_export)\b",
    re.IGNORECASE)
# SQLAlchemy text() 會把 :name 當成綁定參數；查詢裡的冒號（例如 '12:30'）要先跳脫
_BIND_RE = re.compile(r"(?<![:\w\\]):(?=\w)")


@dataclass
class POSConfig:
    url: str = ""
    game_query: str = DEFAULT_GAME_QUERY
    game_mapping: dict = field(default_factory=dict)
    member_query: str = DEFAULT_MEMBER_QUERY
    member_mapping: dict = field(default_factory=dict)
    history_query: str = DEFAULT_HISTORY_QUERY
    history_mapping: dict = field(default_factory=dict)   # member_no / pos_sku / kind / occurred_at
    history_default_kind: str = "buy"                       # 沒有對應 kind 欄時，全部視為這種
    sync_games: bool = True
    sync_members: bool = True
    sync_history: bool = False

    @classmethod
    def load(cls, db: Database) -> "POSConfig":
        data = db.get_setting("pos_config", {}) or {}
        if not isinstance(data, dict):
            data = {}
        cfg = cls()
        for k, v in data.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        return cfg

    def save(self, db: Database) -> None:
        db.set_setting("pos_config", asdict(self))

    _PW_RE = re.compile(r"(://[^:/@]+:)(.+)(@[^@]*)$")   # 密碼取到「最後一個 @」為止

    @property
    def password(self) -> str | None:
        m = self._PW_RE.search(self.url or "")
        return m.group(2) if m else None

    @property
    def masked_url(self) -> str:
        """隱藏密碼後的連線字串，用於畫面顯示。"""
        return self._PW_RE.sub(r"\1****\3", self.url or "")


class POSConnector:
    def __init__(self, config: POSConfig):
        self.config = config

    @staticmethod
    def check_query(sql: str) -> str:
        s = (sql or "").strip().rstrip(";").strip()
        if not s:
            raise ValueError("查詢語法是空的")
        if ";" in s:
            raise ValueError("只能有一段查詢（不可包含分號）")
        if not re.match(r"^(select|with)\b", s, re.IGNORECASE):
            raise ValueError("只允許 SELECT 查詢")
        if "/*!" in s or "/*+" in s:
            raise ValueError("查詢中不可包含 MySQL 可執行註解 /*! */ 或提示 /*+ */")
        if _FORBIDDEN.search(s):
            raise ValueError("查詢中含有不允許的寫入指令")
        return s

    def _engine(self):
        try:
            from sqlalchemy import create_engine
        except ImportError as e:
            raise RuntimeError("尚未安裝 SQLAlchemy，請執行 pip install sqlalchemy") from e
        if not self.config.url:
            raise ValueError("尚未設定 POS 連線字串")
        return create_engine(self.config.url, pool_pre_ping=True)

    def fetch(self, sql: str, limit: int | None = None) -> list[dict]:
        from sqlalchemy import text
        sql = self.check_query(sql)
        engine = self._engine()
        try:
            with engine.connect() as conn:   # 不 commit：離開時自動 rollback
                result = conn.execute(text(_BIND_RE.sub(r"\\:", sql)))
                cols = list(result.keys())
                rows = result.fetchmany(limit) if limit else result.fetchall()
                return [dict(zip(cols, r)) for r in rows]
        finally:
            engine.dispose()

    def test_connection(self) -> str:
        from sqlalchemy import text
        engine = self._engine()
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return "連線成功"
        finally:
            engine.dispose()

    def preview(self, which: str, limit: int = 5) -> list[dict]:
        sql = {"games": self.config.game_query, "members": self.config.member_query,
               "history": self.config.history_query}[which]
        return self.fetch(sql, limit=limit)

    @staticmethod
    def apply_mapping(rows: list[dict], mapping: dict) -> list[dict]:
        """把 POS 欄位改名為本系統欄位；未對應的欄位保留原名，交給別名自動辨識。"""
        mapping = {k: v for k, v in (mapping or {}).items() if v}
        if not mapping:
            return rows
        reverse = {str(pos_col).strip().lower(): ours for ours, pos_col in mapping.items()}
        out = []
        for r in rows:
            nr = {}
            for k, v in r.items():
                kk = str(k).strip().lower()
                if kk in reverse:
                    nr[reverse[kk]] = v
                elif k not in nr:
                    nr[k] = v
            out.append(nr)
        return out

    def sync(self, db: Database) -> dict[str, ImportResult]:
        results: dict[str, ImportResult] = {}
        if self.config.sync_games:
            rows = self.apply_mapping(self.fetch(self.config.game_query), self.config.game_mapping)
            results["games"] = GameImporter(db).import_rows(rows, source="pos")
        if self.config.sync_members:
            rows = self.apply_mapping(self.fetch(self.config.member_query), self.config.member_mapping)
            results["members"] = MemberImporter(db).import_rows(rows, source="pos")
        if self.config.sync_history:
            rows = self.apply_mapping(self.fetch(self.config.history_query), self.config.history_mapping)
            results["history"] = HistoryImporter(db).import_rows(
                rows, source="pos", default_kind=self.config.history_default_kind)
        return results
