"""資料模型：桌遊、會員。"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Optional
from urllib.parse import urlparse

# 系統內部使用的標籤代碼 → 顯示名稱
TAG_LABELS = {
    "party": "歡樂派對",
    "strategy": "策略燒腦",
    "coop": "合作",
    "deduction": "推理陣營",
    "adventure": "故事冒險",
    "family": "家庭親子",
    "couple": "兩人對戰",
    "word": "文字表達",
    "dexterity": "手眼反應",
    "card": "卡牌",
    "economic": "經濟建設",
    "abstract": "抽象棋類",
    "bluff": "心理吹牛",
    "light": "輕鬆小品",
}

# 匯入時可以接受的中文標籤別名
TAG_ALIASES = {v: k for k, v in TAG_LABELS.items()}
TAG_ALIASES.update({
    "派對": "party", "策略": "strategy", "推理": "deduction", "陣營": "deduction",
    "冒險": "adventure", "故事": "adventure", "家庭": "family", "親子": "family",
    "雙人": "couple", "兩人": "couple", "文字": "word", "反應": "dexterity",
    "經濟": "economic", "抽象": "abstract", "吹牛": "bluff", "心理": "bluff",
    "輕度": "light", "小品": "light",
})


def normalize_tags(raw) -> list[str]:
    """把『派對,合作』或『party;coop』等字串轉成內部標籤代碼清單。"""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        parts = list(raw)
    else:
        text = str(raw)
        for sep in ["；", ";", "、", "，", "|", "/"]:
            text = text.replace(sep, ",")
        parts = text.split(",")
    tags = []
    for p in parts:
        p = str(p).strip()
        if not p:
            continue
        key = p.lower()
        code = key if key in TAG_LABELS else TAG_ALIASES.get(p)
        if code and code not in tags:
            tags.append(code)
    return tags


def safe_url(url) -> str:
    """只允許 http(s) 網址；javascript:、data: 等會被清成空字串（防 XSS）。"""
    u = str(url or "").strip()
    if not u:
        return ""
    if u.startswith("//"):
        u = "https:" + u
    try:
        scheme = urlparse(u).scheme.lower()
    except ValueError:
        return ""
    return u if scheme in ("http", "https") else ""


def _clamp(v, lo, hi, default, cast=int):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(f):
        return default
    return cast(min(hi, max(lo, f)))


@dataclass
class BoardGame:
    name: str
    id: Optional[int] = None
    name_en: str = ""
    min_players: int = 2
    max_players: int = 4
    min_time: int = 30          # 分鐘
    max_time: int = 60
    weight: float = 2.0         # 難度 1~5（參考 BGG weight）
    min_age: int = 8
    tags: list[str] = field(default_factory=list)
    description: str = ""
    pos_sku: str = ""           # POS 商品編號，用來同步對應
    price: float = 0.0
    stock: int = 0              # 販售庫存
    rentable: bool = True       # 店內可租借遊玩
    shelf: str = ""             # 櫃位
    youtube_url: str = ""
    youtube_title: str = ""
    youtube_is_search: bool = False   # True 表示只是 YouTube 搜尋頁連結（尚未找到單一影片）
    image_url: str = ""
    active: bool = True
    source: str = "manual"      # manual / import / pos

    @property
    def tag_labels(self) -> list[str]:
        return [TAG_LABELS.get(t, t) for t in self.tags]

    @property
    def players_text(self) -> str:
        if self.min_players == self.max_players:
            return f"{self.min_players} 人"
        return f"{self.min_players}–{self.max_players} 人"

    @property
    def time_text(self) -> str:
        if self.min_time == self.max_time:
            return f"{self.min_time} 分鐘"
        return f"{self.min_time}–{self.max_time} 分鐘"

    @property
    def weight_text(self) -> str:
        w = self.weight
        if w < 1.8:
            return "入門"
        if w < 2.6:
            return "輕中度"
        if w < 3.4:
            return "中度"
        return "重度"

    def sanitize(self) -> "BoardGame":
        """寫入資料庫前把數值夾在合理範圍、網址限 http(s)，避免後續頁面或 SQLite 出錯。"""
        self.name = str(self.name or "").strip()
        self.min_players = _clamp(self.min_players, 1, 99, 2)
        self.max_players = max(self.min_players, _clamp(self.max_players, 1, 99, 4))
        self.min_time = _clamp(self.min_time, 1, 9999, 30)
        self.max_time = max(self.min_time, _clamp(self.max_time, 1, 9999, 60))
        self.weight = _clamp(self.weight, 1.0, 5.0, 2.0, float)
        self.min_age = _clamp(self.min_age, 0, 99, 8)
        self.price = _clamp(self.price, 0, 10_000_000, 0.0, float)
        self.stock = _clamp(self.stock, 0, 1_000_000, 0)
        self.youtube_url = safe_url(self.youtube_url)
        if not self.youtube_url:
            self.youtube_title, self.youtube_is_search = "", False
        self.image_url = safe_url(self.image_url)
        return self

    def to_dict(self) -> dict:
        d = asdict(self)
        d["tags"] = ",".join(self.tags)
        return d


@dataclass
class Member:
    member_no: str
    name: str = ""
    phone: str = ""
    level: str = ""
    points: int = 0             # POS 點數（同步而來，本系統不修改）
    id: Optional[int] = None
    source: str = "manual"
    app_points: int = 0         # 本系統作答送點的點數

    @property
    def masked_name(self) -> str:
        """王小明 → 王○○；沒有姓名時顯示「會員」。"""
        n = (self.name or "").strip()
        return (n[:1] + "○" * max(0, len(n) - 1)) if n else "會員"

    @property
    def masked_phone(self) -> str:
        p = self.phone or ""
        if len(p) >= 7:
            return p[:4] + "***" + p[-3:]
        return p
