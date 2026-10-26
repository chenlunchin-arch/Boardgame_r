"""題目設定（資料驅動）：讀取 / 嚴格驗證 / 儲存。

預設題目在 core/quiz_default.json；後台「題目設定」頁可改，存進 settings 的 quiz_config。
題目型別：
  players     人數（硬條件）。選項需有 min / max
  time        時間。選項需有 min / max（分鐘）
  tags        依類型標籤計分。選項需有 tags {標籤: 0~1}；可選 penalty_tags、kid
  difficulty  依難度計分。選項需有 target（1~5）；可選 max_weight、tags（偏好標籤小加分）
"""
from __future__ import annotations

import copy
import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .models import TAG_LABELS

_BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
DEFAULT_PATH = _BASE / "core" / "quiz_default.json"
SETTING_KEY = "quiz_config"

QUESTION_TYPES = ("players", "time", "tags", "difficulty")
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,29}$")
RESERVED_KEYS = {"member_key", "member_no", "answers"}    # 網頁表單 / API 已使用的欄位名
_VALUE_RE = re.compile(r"^[A-Za-z0-9_+\-]{1,20}$")


@dataclass
class QuizOption:
    value: str
    label: str
    emoji: str = ""
    min: int = 0
    max: int = 0
    tags: dict = field(default_factory=dict)
    penalty_tags: dict = field(default_factory=dict)
    kid: bool = False
    target: float = 2.0
    max_weight: Optional[float] = None
    reason: str = ""


@dataclass
class QuizQuestion:
    key: str
    type: str
    title: str
    subtitle: str = ""
    short: str = ""
    weight: float = 0
    bonus: float = 5          # difficulty 題：偏好標籤的小加分上限
    options: list[QuizOption] = field(default_factory=list)

    def option(self, value) -> Optional[QuizOption]:
        return next((o for o in self.options if o.value == value), None)

    # 給模板相容（舊版 QUESTIONS 用法）
    @property
    def label(self) -> str:
        return self.short or self.title


@dataclass
class QuizConfig:
    questions: list[QuizQuestion]
    stock_weight: float = 5
    duo_bonus: float = 10
    kid_age: int = 12
    kid_penalty: float = 40
    raw: dict = field(default_factory=dict)

    def question(self, key: str) -> Optional[QuizQuestion]:
        return next((q for q in self.questions if q.key == key), None)

    def first_of_type(self, qtype: str) -> Optional[QuizQuestion]:
        return next((q for q in self.questions if q.type == qtype), None)

    # ---------- 讀取 ----------
    @classmethod
    def default_dict(cls) -> dict:
        return json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))

    @classmethod
    def default(cls) -> "QuizConfig":
        return cls.from_dict(cls.default_dict())

    @classmethod
    def load(cls, db) -> "QuizConfig":
        """讀 settings；沒有或資料損壞時退回預設題目（不讓前台壞掉）。"""
        data = db.get_setting(SETTING_KEY)
        if isinstance(data, dict):
            try:
                return cls.from_dict(data)
            except ValueError:
                pass
        return cls.default()

    @classmethod
    def from_dict(cls, data: dict) -> "QuizConfig":
        clean = validate_quiz(data)
        qs = []
        for q in clean["questions"]:
            opts = [QuizOption(**o) for o in q["options"]]
            qs.append(QuizQuestion(key=q["key"], type=q["type"], title=q["title"],
                                   subtitle=q["subtitle"], short=q["short"], weight=q["weight"],
                                   bonus=q["bonus"], options=opts))
        return cls(questions=qs, stock_weight=clean["stock_weight"], duo_bonus=clean["duo_bonus"],
                   kid_age=clean["kid_age"], kid_penalty=clean["kid_penalty"], raw=clean)

    def to_json(self) -> str:
        return json.dumps(self.raw, ensure_ascii=False, indent=2)

    # ---------- 給 API / 前台 ----------
    def public_questions(self) -> list[dict]:
        return [{"key": q.key, "title": q.title, "subtitle": q.subtitle,
                 "options": [{"value": o.value, "label": o.label, "emoji": o.emoji} for o in q.options]}
                for q in self.questions]

    def summary(self, answers: dict) -> list[tuple[str, str]]:
        """把答案轉成 (題目簡稱, 選項文字)。舊紀錄（題目已改）會原樣顯示。"""
        answers = answers if isinstance(answers, dict) else {}
        out, seen = [], set()
        for q in self.questions:
            if q.key not in answers:
                continue
            seen.add(q.key)
            v = answers.get(q.key)
            opt = q.option(v)
            out.append((q.label, f"{opt.emoji} {opt.label}".strip() if opt else str(v)))
        for k, v in answers.items():
            if k not in seen:
                out.append((str(k), str(v)))
        return out


# ====================================================================== 驗證
def _num(v, name: str, lo: float, hi: float, integer: bool = False):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"{name} 必須是數字")
    if not math.isfinite(v) or v < lo or v > hi:
        raise ValueError(f"{name} 必須介於 {lo} 到 {hi}")
    if integer:
        if float(v) != int(v):
            raise ValueError(f"{name} 必須是整數")
        return int(v)
    return float(v)


def _text(v, name: str, max_len: int, required: bool = True) -> str:
    if v is None and not required:
        return ""
    if not isinstance(v, str):
        raise ValueError(f"{name} 必須是文字")
    v = v.strip()
    if required and not v:
        raise ValueError(f"{name} 不可空白")
    if len(v) > max_len:
        raise ValueError(f"{name} 最多 {max_len} 個字")
    return v


def _tag_weights(v, name: str) -> dict:
    if v is None:
        return {}
    if not isinstance(v, dict):
        raise ValueError(f"{name} 必須是 {{\"標籤\": 權重}} 的格式")
    out = {}
    for t, w in v.items():
        if t not in TAG_LABELS:
            raise ValueError(f"{name} 有不認得的標籤「{t}」（可用：{', '.join(TAG_LABELS)}）")
        out[t] = _num(w, f"{name}.{t}", 0, 1)
    return out


_ALLOWED_TOP = {"version", "stock_weight", "duo_bonus", "kid_age", "kid_penalty", "questions"}
_ALLOWED_Q = {"key", "type", "short", "title", "subtitle", "weight", "bonus", "options"}
_ALLOWED_O = {"value", "label", "emoji", "min", "max", "tags", "penalty_tags", "kid", "target",
              "max_weight", "reason"}


def validate_quiz(data) -> dict:
    """嚴格驗證題目設定，回傳正規化後的 dict；有問題丟 ValueError（訊息給店員看）。"""
    if not isinstance(data, dict):
        raise ValueError("最外層必須是 { ... } 物件")
    extra = set(data) - _ALLOWED_TOP
    if extra:
        raise ValueError(f"不認得的設定：{', '.join(sorted(extra))}")
    out = {
        "version": 2,
        "stock_weight": _num(data.get("stock_weight", 5), "stock_weight", 0, 30),
        "duo_bonus": _num(data.get("duo_bonus", 10), "duo_bonus", 0, 30),
        "kid_age": _num(data.get("kid_age", 12), "kid_age", 0, 21, integer=True),
        "kid_penalty": _num(data.get("kid_penalty", 40), "kid_penalty", 0, 100),
    }
    qs = data.get("questions")
    if not isinstance(qs, list) or not 2 <= len(qs) <= 8:
        raise ValueError("questions 必須是 2 到 8 題的清單")
    keys = set()
    clean_qs = []
    for qi, q in enumerate(qs, start=1):
        where = f"第 {qi} 題"
        if not isinstance(q, dict):
            raise ValueError(f"{where} 格式錯誤")
        extra = set(q) - _ALLOWED_Q
        if extra:
            raise ValueError(f"{where} 有不認得的欄位：{', '.join(sorted(extra))}")
        key = q.get("key")
        if not isinstance(key, str) or not _KEY_RE.match(key):
            raise ValueError(f"{where} 的 key 只能用小寫英文、數字、底線，且英文開頭")
        if key in RESERVED_KEYS:
            raise ValueError(f"{where} 的 key「{key}」是系統保留字，請換一個")
        if key in keys:
            raise ValueError(f"{where} 的 key「{key}」重複")
        keys.add(key)
        where = f"題目「{key}」"
        qtype = q.get("type")
        if qtype not in QUESTION_TYPES:
            raise ValueError(f"{where} 的 type 必須是 {', '.join(QUESTION_TYPES)} 之一")
        cq = {
            "key": key, "type": qtype,
            "title": _text(q.get("title"), f"{where} 的 title", 60),
            "subtitle": _text(q.get("subtitle", ""), f"{where} 的 subtitle", 80, required=False),
            "short": _text(q.get("short", ""), f"{where} 的 short", 10, required=False),
            "weight": _num(q.get("weight", 0), f"{where} 的 weight", 0, 60),
            "bonus": _num(q.get("bonus", 5), f"{where} 的 bonus", 0, 20),
        }
        opts = q.get("options")
        if not isinstance(opts, list) or not 2 <= len(opts) <= 8:
            raise ValueError(f"{where} 的 options 必須是 2 到 8 個選項")
        values = set()
        clean_opts = []
        for oi, o in enumerate(opts, start=1):
            ow = f"{where} 第 {oi} 個選項"
            if not isinstance(o, dict):
                raise ValueError(f"{ow} 格式錯誤")
            extra = set(o) - _ALLOWED_O
            if extra:
                raise ValueError(f"{ow} 有不認得的欄位：{', '.join(sorted(extra))}")
            val = o.get("value")
            if not isinstance(val, str) or not _VALUE_RE.match(val):
                raise ValueError(f"{ow} 的 value 只能用英數字與 _ + -（1~20 字）")
            if val in values:
                raise ValueError(f"{ow} 的 value「{val}」重複")
            values.add(val)
            co = {"value": val,
                  "label": _text(o.get("label"), f"{ow} 的 label", 30),
                  "emoji": _text(o.get("emoji", ""), f"{ow} 的 emoji", 16, required=False),
                  "reason": _text(o.get("reason", ""), f"{ow} 的 reason", 60, required=False)}
            if qtype in ("players", "time"):
                hi = 99 if qtype == "players" else 1440
                lo = 1 if qtype == "players" else 0
                co["min"] = _num(o.get("min"), f"{ow} 的 min", lo, hi, integer=True)
                co["max"] = _num(o.get("max"), f"{ow} 的 max", lo, hi, integer=True)
                if co["min"] > co["max"]:
                    raise ValueError(f"{ow} 的 min 不可大於 max")
            elif qtype == "tags":
                co["tags"] = _tag_weights(o.get("tags"), f"{ow} 的 tags")
                if not co["tags"]:
                    raise ValueError(f"{ow} 至少要有一個 tags")
                co["penalty_tags"] = _tag_weights(o.get("penalty_tags"), f"{ow} 的 penalty_tags")
                kid = o.get("kid", False)
                if not isinstance(kid, bool):
                    raise ValueError(f"{ow} 的 kid 必須是 true 或 false")
                co["kid"] = kid
            else:   # difficulty
                co["target"] = _num(o.get("target"), f"{ow} 的 target", 1, 5)
                mw = o.get("max_weight")
                co["max_weight"] = None if mw is None else _num(mw, f"{ow} 的 max_weight", 1, 5)
                co["tags"] = _tag_weights(o.get("tags"), f"{ow} 的 tags")
            clean_opts.append(co)
        cq["options"] = clean_opts
        clean_qs.append(cq)
    types = [q["type"] for q in clean_qs]
    if types.count("players") != 1:
        raise ValueError("必須剛好有一題 type 為 players（人數）")
    if types.count("time") > 1:
        raise ValueError("type 為 time 的題目最多一題")
    out["questions"] = clean_qs
    return out


def parse_quiz_json(text: str) -> dict:
    """後台 textarea → 驗證過的 dict。"""
    try:
        data = json.loads(text or "")
    except ValueError as e:
        raise ValueError(f"JSON 格式錯誤（第 {getattr(e, 'lineno', '?')} 行）：{getattr(e, 'msg', e)}") from e
    return validate_quiz(data)


def format_reason(template: str, **values) -> str:
    """用簡單取代填入 {time_text} 等欄位（不用 str.format，避免店員輸入的大括號出錯或被濫用）。"""
    s = template or ""
    for k, v in values.items():
        s = s.replace("{" + k + "}", str(v))
    return s


def deep_copy_default() -> dict:
    return copy.deepcopy(QuizConfig.default_dict())
