"""搜尋桌遊的 YouTube 教學影片。

有設定 YouTube Data API v3 金鑰時：呼叫官方搜尋 API，挑出最像「教學」的影片。
沒有金鑰時：產生 YouTube 搜尋頁連結（點了會開出搜尋結果），之後可再補金鑰批次更新。
"""
from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

from .models import BoardGame

API_URL = "https://www.googleapis.com/youtube/v3/search"

# 標題含這些字詞的影片加分
GOOD_WORDS = ["教學", "規則", "怎麼玩", "玩法", "說明", "how to play", "rules", "tutorial", "teach"]
BAD_WORDS = ["開箱", "unboxing", "review", "評測", "實況", "直播", "live", "shorts"]

_ID_PATTERNS = [
    re.compile(r"youtu\.be/([A-Za-z0-9_-]{11})"),
    re.compile(r"[?&]v=([A-Za-z0-9_-]{11})"),
    re.compile(r"youtube\.com/(?:embed|shorts|live)/([A-Za-z0-9_-]{11})"),
]


@dataclass
class VideoResult:
    url: str
    title: str
    is_search: bool = False
    channel: str = ""


def extract_video_id(url: str) -> Optional[str]:
    for p in _ID_PATTERNS:
        m = p.search(url or "")
        if m:
            return m.group(1)
    return None


def embed_url(url: str) -> Optional[str]:
    vid = extract_video_id(url)
    return f"https://www.youtube-nocookie.com/embed/{vid}" if vid else None


def search_page_url(query: str) -> str:
    return "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)


class YouTubeFinder:
    def __init__(self, api_key: str = "", region: str = "TW", language: str = "zh-Hant",
                 http_get: Optional[Callable[[str], dict]] = None):
        self.api_key = (api_key or "").strip()
        self.region = region
        self.language = language
        self._http_get = http_get or self._default_get

    @staticmethod
    def _default_get(url: str) -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": "BoardGameRecommender/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")
            try:
                msg = json.loads(body)["error"]["message"]
            except Exception:
                msg = body[:200]
            raise RuntimeError(f"YouTube API 錯誤（{e.code}）：{msg}") from e

    @staticmethod
    def build_queries(game: BoardGame) -> list[str]:
        qs = [f"{game.name} 桌遊 教學"]
        if game.name_en:
            qs.append(f"{game.name_en} board game how to play")
        return qs

    @staticmethod
    def score_title(title: str, game: BoardGame) -> float:
        t = title.lower()
        s = 0.0
        if game.name and game.name.lower() in t:
            s += 3
        if game.name_en and game.name_en.lower() in t:
            s += 2
        s += sum(1.5 for w in GOOD_WORDS if w in t)
        s -= sum(2 for w in BAD_WORDS if w in t)
        return s

    def _api_search(self, query: str, max_results: int = 8) -> list[dict]:
        params = {
            "part": "snippet", "q": query, "type": "video", "maxResults": max_results,
            "regionCode": self.region, "relevanceLanguage": self.language,
            "safeSearch": "strict", "videoEmbeddable": "true", "key": self.api_key,
        }
        data = self._http_get(API_URL + "?" + urllib.parse.urlencode(params))
        return data.get("items", [])

    def find(self, game: BoardGame) -> VideoResult:
        queries = self.build_queries(game)
        if not self.api_key:
            return VideoResult(search_page_url(queries[0]), f"在 YouTube 搜尋「{queries[0]}」", True)

        best: Optional[tuple[float, int, dict]] = None
        for qi, q in enumerate(queries):
            for rank, item in enumerate(self._api_search(q)):
                vid = item.get("id", {}).get("videoId")
                if not vid:
                    continue
                title = item.get("snippet", {}).get("title", "")
                # 排名越前面越好；中文查詢優先
                score = self.score_title(title, game) - rank * 0.3 - qi * 0.5
                if best is None or score > best[0]:
                    best = (score, rank, item)
            if best and best[0] >= 4:      # 中文查詢已找到很好的結果，就不再查英文，省配額
                break

        if best is None:
            return VideoResult(search_page_url(queries[0]), f"在 YouTube 搜尋「{queries[0]}」", True)
        item = best[2]
        sn = item["snippet"]
        return VideoResult(
            url=f"https://www.youtube.com/watch?v={item['id']['videoId']}",
            title=html.unescape(sn.get("title", "")),
            channel=html.unescape(sn.get("channelTitle", "")),
        )
