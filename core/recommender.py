"""資料驅動的選擇題推薦引擎（第 2 版）。

題目與每個選項的權重存在 core/quiz_default.json（後台可改，存在 settings.quiz_config）。

計分（預設滿分約 100）：
  1. 人數（players 題）：硬條件，不符合的遊戲直接排除；全部被排除時放寬，取人數最接近者。
     選 2 人時，兩人專屬遊戲額外加 duo_bonus。
  2. 時間（time 題）25：遊戲平均時長落在區間內滿分，離越遠分數越低。
  3. 類型題（tags，例如動物 30、贏的台詞 15）：遊戲標籤命中選項中權重最高者得分（1.0 / 0.8 / 0.45…）；
     penalty_tags 扣分；kid=true 時 min_age >= kid_age 的遊戲大幅扣分。
  4. 難度題（difficulty，宵夜 25）：與目標難度的差距；超過 max_weight（新手保護）再打折；偏好標籤小加分。
  5. 店內可玩／有庫存 5。
  6. 會員個人化：依歷史遊戲的標籤分布與平均難度，最多 +10。
會員玩過／買過的遊戲先排除；不足 top_n 時才用玩過的補位，理由標示「你玩過，值得再開一局」。
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from .models import BoardGame
from .quiz import QuizConfig, QuizQuestion, format_reason

PERSONAL_MAX = 10.0
PLAYED_REASON = "你玩過，值得再開一局"


@dataclass
class Recommendation:
    game: BoardGame
    score: float
    reasons: list[str] = field(default_factory=list)
    played_before: bool = False

    @property
    def match_percent(self) -> int:
        return max(1, min(99, round(self.score)))


@dataclass
class MemberProfile:
    """會員歷史：played_ids 用來排除；history 用來算個人化加分。"""
    played_ids: set = field(default_factory=set)
    history: list = field(default_factory=list)          # list[BoardGame]
    counts: dict = field(default_factory=dict)           # game_id → 次數

    @property
    def has_history(self) -> bool:
        return bool(self.history)


class Recommender:
    """依問答結果計算每款遊戲的契合度。"""

    def __init__(self, games: list[BoardGame], config: Optional[QuizConfig] = None):
        self.games = [g for g in games if g.active]
        self.config = config or QuizConfig.default()
        self.last_excluded = 0      # 上次推薦因「玩過」被排除（且沒被拿來補位）的款數

    # ---- 驗證 ----
    def validate(self, answers) -> dict:
        if not isinstance(answers, dict):
            raise ValueError("答案格式不正確")
        clean = {}
        for q in self.config.questions:
            v = answers.get(q.key)
            if not isinstance(v, str) or q.option(v) is None:
                raise ValueError(f"題目「{q.title}」的答案不正確：{v!r}")
            clean[q.key] = v
        return clean

    # ---- 主流程 ----
    def recommend(self, answers: dict, top_n: int = 5,
                  profile: Optional[MemberProfile] = None) -> list[Recommendation]:
        answers = self.validate(answers)
        pq = self.config.first_of_type("players")
        popt = pq.option(answers[pq.key])
        lo, hi = popt.min, popt.max
        fits = [g for g in self.games if g.min_players <= hi and g.max_players >= lo]
        relaxed = False
        if not fits:
            relaxed = True
            fits = sorted(self.games, key=lambda g: (self._player_gap(g, lo, hi), g.name, g.id or 0))[:top_n * 3]

        taste = self._taste(profile) if profile and profile.has_history else None
        recs = [self._score(g, answers, relaxed, lo, hi, profile, taste) for g in fits]
        recs.sort(key=lambda r: (-r.score, r.game.name, r.game.id or 0))

        played = profile.played_ids if profile else set()
        fresh = [r for r in recs if r.game.id not in played]
        out = fresh[:top_n]
        if len(out) < top_n:
            for r in recs:
                if len(out) >= top_n:
                    break
                if r.game.id in played:
                    r.played_before = True
                    r.reasons.insert(0, PLAYED_REASON)
                    out.append(r)
        self.last_excluded = sum(1 for r in recs if r.game.id in played and not r.played_before)
        return out

    @staticmethod
    def _player_gap(g: BoardGame, lo: int, hi: int) -> int:
        if g.max_players < lo:
            return lo - g.max_players
        if g.min_players > hi:
            return g.min_players - hi
        return 0

    # ---- 個人化 ----
    @staticmethod
    def _taste(profile: MemberProfile) -> dict:
        n = len(profile.history)
        tag_freq: Counter = Counter()
        for h in profile.history:
            for t in set(h.tags):
                tag_freq[t] += 1
        avg_w = sum(h.weight for h in profile.history) / n
        return {"freq": {t: c / n for t, c in tag_freq.items()}, "avg_w": avg_w}

    @staticmethod
    def _closest_history(g: BoardGame, profile: MemberProfile) -> Optional[BoardGame]:
        gt = set(g.tags)
        best, best_key = None, None
        for h in profile.history:
            if h.id == g.id:
                continue
            ht = set(h.tags)
            if not gt or not ht:
                continue
            jac = len(gt & ht) / len(gt | ht)
            if jac <= 0:
                continue
            key = (jac, profile.counts.get(h.id, 1), -abs(h.weight - g.weight))
            if best_key is None or key > best_key:
                best, best_key = h, key
        return best

    def _personal(self, g: BoardGame, profile: MemberProfile, taste: dict) -> tuple[float, str]:
        if not g.tags:
            return 0.0, ""
        freq = taste["freq"]
        sim_tag = sum(freq.get(t, 0.0) for t in g.tags) / len(g.tags)
        if sim_tag <= 0:
            return 0.0, ""
        sim_w = max(0.0, 1 - abs(g.weight - taste["avg_w"]) / 1.5)
        bonus = PERSONAL_MAX * min(1.0, 0.7 * min(1.0, sim_tag * 1.5) + 0.3 * sim_w)
        reason = ""
        if bonus >= 4:
            h = self._closest_history(g, profile)
            if h is not None:
                reason = f"和你常玩的《{h.name}》風格相近"
        return bonus, reason

    # ---- 單款計分 ----
    def _score(self, g: BoardGame, a: dict, relaxed: bool, lo: int, hi: int,
               profile: Optional[MemberProfile], taste: Optional[dict]) -> Recommendation:
        cfg = self.config
        reasons: list[str] = []
        score = 0.0
        tagset = set(g.tags)
        duo_wanted = (lo, hi) == (2, 2)
        is_duo = g.max_players == 2 and g.min_players <= 2

        # 人數
        if relaxed:
            reasons.append(f"人數最接近（{g.players_text}）")
        elif duo_wanted and is_duo:
            reasons.append("兩人專屬，剛好適合你們倆")
            score += cfg.duo_bonus
        else:
            reasons.append(f"支援 {g.players_text}")

        for q in cfg.questions:
            opt = q.option(a[q.key])
            if q.type == "time":
                score += self._score_time(g, q, opt, reasons)
            elif q.type == "tags":
                score += self._score_tags(g, q, opt, tagset, reasons)
            elif q.type == "difficulty":
                score += self._score_difficulty(g, q, opt, tagset, reasons)

        # 庫存 / 可租
        if g.rentable or g.stock > 0:
            score += cfg.stock_weight
            if g.rentable:
                reasons.append("店內可以馬上開玩")

        # 會員個人化
        if taste is not None:
            bonus, why = self._personal(g, profile, taste)
            score += bonus
            if why:
                reasons.append(why)

        return Recommendation(g, max(0.0, score), reasons)

    @staticmethod
    def _score_time(g: BoardGame, q: QuizQuestion, opt, reasons: list) -> float:
        t_lo, t_hi = opt.min, opt.max
        g_mid = (g.min_time + g.max_time) / 2
        if t_lo <= g_mid <= t_hi:
            s = 1.0
        else:
            dist = (t_lo - g_mid) if g_mid < t_lo else (g_mid - t_hi)
            # 衰減幅度最多 60 分鐘：否則「2 小時以上（120~600）」會讓 30 分鐘的遊戲仍拿 0.8 分、
            # 還被寫上「適合長時間開戰」
            s = max(0.0, 1 - dist / max(30, min(60, t_hi - t_lo)))
        if s >= 0.8:
            reasons.append(format_reason(opt.reason or "約 {time_text}，時間剛好", time_text=g.time_text))
        return q.weight * s

    def _score_tags(self, g: BoardGame, q: QuizQuestion, opt, tagset: set, reasons: list) -> float:
        s = max((w for t, w in opt.tags.items() if t in tagset), default=0.0)
        pen = max((w for t, w in opt.penalty_tags.items() if t in tagset), default=0.0)
        pts = q.weight * (s - pen)
        if opt.kid and g.min_age >= self.config.kid_age:
            pts -= self.config.kid_penalty
        if s >= 0.7 and pen == 0 and not (opt.kid and g.min_age >= self.config.kid_age):
            reasons.append(format_reason(opt.reason or f"符合『{opt.label}』", label=opt.label))
        return pts

    @staticmethod
    def _score_difficulty(g: BoardGame, q: QuizQuestion, opt, tagset: set, reasons: list) -> float:
        diff = abs(g.weight - opt.target)
        s = max(0.0, 1 - diff / 1.6)
        if opt.max_weight is not None and g.weight > opt.max_weight:
            s *= 0.3            # 超過這個宵夜能接受的難度 → 新手保護
        pts = q.weight * s
        pref = max((w for t, w in opt.tags.items() if t in tagset), default=0.0)
        pts += q.bonus * pref
        if s >= 0.75:
            reasons.append(format_reason(opt.reason or f"難度像{opt.label}：{{weight_text}}",
                                         weight_text=g.weight_text, label=opt.label))
        return pts


def answers_summary(answers: dict, config: Optional[QuizConfig] = None) -> list[tuple[str, str]]:
    """把答案轉成可讀的 (題目, 選項) 清單，給結果頁與後台使用。"""
    return (config or QuizConfig.default()).summary(answers)
