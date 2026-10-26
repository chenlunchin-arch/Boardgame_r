"""桌遊推薦 APP — Flask 主程式（第 2 版）。

平板 API：http://本機IP:5000/api/v1/...  Android 平板 APP 前台（需裝置金鑰 X-Device-Key）
網頁前台：http://本機IP:5000/            備用前台：會員（可略過）→ 5 題 → 推薦 + YouTube 教學
後台：    http://本機IP:5000/admin       桌遊、題目設定、平板配對、匯入匯出、POS、會員點數、問答紀錄
"""
from __future__ import annotations

import math
import os
import secrets
import socket
import sys
import threading
import time
from collections import OrderedDict
from datetime import datetime
from functools import wraps
from pathlib import Path

from urllib.parse import urlparse

from flask import (Flask, Response, abort, flash, g, jsonify, redirect, render_template,
                   request, session, url_for)
from werkzeug.exceptions import HTTPException
from werkzeug.routing import IntegerConverter
from werkzeug.security import check_password_hash, generate_password_hash

from core.database import Database
from core.importer import GameImporter, HistoryImporter, MemberImporter, TableReader, normalize_phone
from core.models import BoardGame, Member, TAG_LABELS, normalize_tags
from core.pos_connector import POSConfig, POSConnector
from core.quiz import SETTING_KEY as QUIZ_SETTING_KEY, QuizConfig, parse_quiz_json
from core.recommender import MemberProfile, Recommender
from core.youtube_finder import YouTubeFinder, embed_url, extract_video_id, search_page_url

API_VERSION = "2.0"

BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
# 打包成 exe 時 __file__ 在暫存資料夾，資料要放在 exe 旁邊才不會每次重開就消失
_APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
    else Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("BGR_DATA_DIR") or _APP_DIR / "data")


def safe_next(url: str | None, fallback: str) -> str:
    """只允許站內相對路徑，擋掉 //evil.com、/\\evil.com、https://evil.com 等 open redirect。"""
    u = (url or "").strip()
    if not u or not u.startswith("/") or u.startswith("//") or "\\" in u:
        return fallback
    p = urlparse(u)
    if p.scheme or p.netloc:
        return fallback
    return u


def to_int(v, default: int, lo: int | None = None, hi: int | None = None) -> int:
    try:
        n = int(float(str(v).strip()))
    except (TypeError, ValueError, OverflowError):
        n = default
    if lo is not None:
        n = max(lo, n)
    if hi is not None:
        n = min(hi, n)
    return n


DEFAULT_PASSWORD = "admin1234"


class SafeIntConverter(IntegerConverter):
    """<int:...> 限制在 SQLite INTEGER 範圍內：超大的 id 直接 404，不會 OverflowError → 500。"""
    def __init__(self, map, *args, **kwargs):
        kwargs.setdefault("max", 2 ** 63 - 1)
        super().__init__(map, *args, **kwargs)


def create_app(db_path: str | Path | None = None) -> Flask:
    app = Flask(__name__, template_folder=str(BASE_DIR / "templates"),
                static_folder=str(BASE_DIR / "static"))
    app.url_map.converters["int"] = SafeIntConverter
    db = Database(db_path or DATA_DIR / "boardgames.db")
    app.config["DB"] = db

    # 第一次啟動：產生 session 金鑰與預設管理密碼
    secret = db.get_setting("secret_key")
    if not secret:
        secret = secrets.token_hex(32)
        db.set_setting("secret_key", secret)
    app.secret_key = secret
    if not db.get_setting("admin_password_hash"):
        db.set_setting("admin_password_hash", generate_password_hash(DEFAULT_PASSWORD))
        db.set_setting("password_is_default", True)
    app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_HTTPONLY"] = True

    # ------------------------------------------------------------ 共用
    def settings() -> dict:
        return {
            "store_name": db.get_setting("store_name", "桌遊小幫手"),
            "top_n": to_int(db.get_setting("top_n", 5), 5, 1, 20),
            "allow_member": bool(db.get_setting("allow_member", True)),
            "youtube_api_key": db.get_setting("youtube_api_key", ""),
            "show_price": bool(db.get_setting("show_price", True)),
            "points_per_quiz": to_int(db.get_setting("points_per_quiz", 10), 10, 0, 100000),
            "points_daily_limit": to_int(db.get_setting("points_daily_limit", 1), 1, 0, 100),
        }

    def is_api() -> bool:
        return request.path.startswith("/api/")

    def api_error(status: int, message: str, **extra):
        body = {"ok": False, "error": message, "message": message}
        body.update(extra)
        return jsonify(body), status

    @app.before_request
    def _load():
        g.db = db
        g.settings = settings()
        g.quiz = QuizConfig.load(db)
        if is_api():
            # 平板 API：不用 cookie / CSRF，改用裝置金鑰
            dev = db.get_device_by_key((request.headers.get("X-Device-Key") or "").strip())
            if dev is None:
                return api_error(401, "裝置金鑰無效或已停用，請到後台「平板配對」重新設定")
            g.device = dev
            db.touch_device(dev["id"], request.remote_addr or "")
            return None
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(16)
        if request.method == "POST":
            token = request.form.get("_csrf") or request.headers.get("X-CSRF") or ""
            if not secrets.compare_digest(str(token), str(session.get("csrf", ""))):
                abort(400, "表單已過期，請重新整理頁面")

    @app.context_processor
    def _inject():
        if "settings" not in g:          # 例如 before_request 本身出錯時的錯誤頁
            g.settings = {"store_name": "桌遊小幫手", "top_n": 5, "allow_member": False,
                          "youtube_api_key": "", "show_price": False, "points_per_quiz": 0,
                          "points_daily_limit": 0}
        return {"S": g.settings, "csrf": session.get("csrf", ""), "TAG_LABELS": TAG_LABELS,
                "embed_url": embed_url}

    def admin_required(view):
        @wraps(view)
        def wrapper(*a, **kw):
            if not session.get("admin"):
                return redirect(url_for("admin_login", next=request.path))
            return view(*a, **kw)
        return wrapper

    def youtube_finder() -> YouTubeFinder:
        return YouTubeFinder(api_key=g.settings["youtube_api_key"])

    def quiz() -> QuizConfig:
        return g.get("quiz") or QuizConfig.load(db)

    def summarize(answers) -> list:
        return quiz().summary(answers)

    # 會員查詢節流：避免有人用平板或網頁大量猜手機號碼
    _lookup_hits: "OrderedDict[str, list[float]]" = OrderedDict()
    _lookup_lock = threading.Lock()
    LOOKUP_LIMIT = 20          # 每分鐘
    LOOKUP_MAX_KEYS = 5000

    def lookup_allowed(*whos: str) -> bool:
        """所有 key 都還有額度才放行並各記一次（任一被擋就都不記，避免被擋的請求一直產生新 key）。

        字典只清掉「60 秒內沒有紀錄」的 key；真的塞滿才淘汰最久沒動的，被擋中的 key 一定是剛用過的，
        不會像舊版那樣被灌新 session 擠掉而重置額度。
        """
        now = time.monotonic()
        with _lookup_lock:
            fresh = {w: [t for t in _lookup_hits.get(w, ()) if now - t < 60] for w in whos}
            if any(len(h) >= LOOKUP_LIMIT for h in fresh.values()):
                for w, h in fresh.items():
                    if w in _lookup_hits:
                        _lookup_hits[w] = h
                        _lookup_hits.move_to_end(w)
                return False
            for w, h in fresh.items():
                h.append(now)
                _lookup_hits[w] = h
                _lookup_hits.move_to_end(w)
            max_keys = app.config.get("LOOKUP_MAX_KEYS", LOOKUP_MAX_KEYS)
            if len(_lookup_hits) > max_keys:
                for k in [k for k, h in _lookup_hits.items() if not h or now - h[-1] >= 60]:
                    del _lookup_hits[k]
                while len(_lookup_hits) > max_keys:
                    _lookup_hits.popitem(last=False)
            return True

    def web_lookup_keys() -> tuple[str, str]:
        return "web:" + str(session.get("csrf")), "ip:" + str(request.remote_addr)

    def find_member_by_key(key) -> Member | None:
        key = str(key or "").strip()[:40]
        if not key:
            return None
        return db.find_member(key) or db.find_member(normalize_phone(key))

    def member_profile(m: Member | None, all_games: list[BoardGame]) -> MemberProfile | None:
        if m is None:
            return None
        counts = db.history_game_counts(m.member_no)
        by_id = {x.id: x for x in all_games}
        return MemberProfile(played_ids=set(counts), counts=counts,
                             history=[by_id[i] for i in counts if i in by_id])

    def run_recommend(answers: dict, m: Member | None):
        """回傳 (推薦清單, 排除款數, profile)。答案不合法丟 ValueError。"""
        all_games = db.list_games()
        prof = member_profile(m, all_games)
        rec = Recommender(all_games, quiz())
        recs = rec.recommend(answers, top_n=g.settings["top_n"], profile=prof)
        return recs, rec.last_excluded, prof

    def greeting_of(m: Member) -> str:
        return f"{m.masked_name} 您好！"

    # ------------------------------------------------------------ 前台（網頁備用）
    @app.route("/")
    def index():
        return render_template("index.html", questions=quiz().questions,
                               game_count=db.count_games()["active"])

    @app.route("/member/lookup", methods=["POST"])
    def web_member_lookup():
        if not g.settings["allow_member"]:
            return {"ok": False, "message": "目前未開放會員功能"}, 403
        if not lookup_allowed(*web_lookup_keys()):
            return {"ok": False, "message": "查詢太頻繁，請稍後再試"}, 429
        m = find_member_by_key(request.form.get("member_key"))
        if m is None:
            return {"ok": False, "message": "查不到這個會員，可以先略過或洽櫃檯"}
        return {"ok": True, "greeting": greeting_of(m), "points": m.app_points}

    @app.route("/result", methods=["GET", "POST"])
    def result():
        if request.method == "GET":
            return redirect(url_for("index"))
        answers = {q.key: request.form.get(q.key) for q in quiz().questions}
        member = None
        member_key = (request.form.get("member_key") or "").strip()
        if member_key and g.settings["allow_member"]:
            # 這裡也會查會員：同樣要節流，否則可繞過 /member/lookup 的限制大量猜手機號碼
            if not lookup_allowed(*web_lookup_keys()):
                flash("會員查詢太頻繁，這次先不使用會員推薦", "warn")
            elif (member := find_member_by_key(member_key)) is None:
                flash("查不到這個會員，這次先不使用會員推薦", "warn")
        try:
            recs, excluded, prof = run_recommend(answers, member)
        except ValueError as e:
            flash(str(e), "error")
            return redirect(url_for("index"))
        log_id = db.add_quiz_log(answers, [r.game.id for r in recs])
        member_info = None
        if member is not None:
            ok, added, total, msg = db.claim_quiz_points(
                log_id, member.member_no, g.settings["points_per_quiz"], g.settings["points_daily_limit"])
            member_info = {"greeting": greeting_of(member), "excluded_count": excluded,
                           "personalized": bool(prof and prof.has_history), "points_msg": msg,
                           "points_added": added}
        else:
            # 只允許把「這台裝置剛產生的」推薦紀錄綁到會員，避免猜 log_id 灌別人的紀錄
            session["my_logs"] = (session.get("my_logs") or [])[-19:] + [log_id]
        return render_template("result.html", recs=recs, summary=summarize(answers),
                               log_id=log_id, member_info=member_info)

    @app.route("/result/<int:log_id>/member", methods=["POST"])
    def result_member(log_id: int):
        if not g.settings["allow_member"]:
            abort(404)
        if log_id not in (session.get("my_logs") or []) or db.get_quiz_log(log_id) is None:
            return {"ok": False, "message": "這次推薦已過期，請重新回答一次"}
        if not lookup_allowed(*web_lookup_keys()):
            return {"ok": False, "message": "查詢太頻繁，請稍後再試"}, 429
        m = find_member_by_key(request.form.get("member_key"))
        if m is None:
            return {"ok": False, "message": "查不到這個會員，請洽櫃檯"}
        ok, added, total, msg = db.claim_quiz_points(
            log_id, m.member_no, g.settings["points_per_quiz"], g.settings["points_daily_limit"])
        if not ok:
            return {"ok": False, "message": msg}
        session["my_logs"] = [x for x in (session.get("my_logs") or []) if x != log_id]
        return {"ok": True, "message": f"{m.masked_name} 您好，{msg}", "points_added": added}

    @app.route("/game/<int:game_id>")
    def game_detail(game_id: int):
        game = db.get_game(game_id)
        if not game or not game.active:
            abort(404)
        return render_template("game.html", game=game)

    @app.route("/browse")
    def browse():
        q = request.args.get("q", "").strip()[:100]
        tag = request.args.get("tag", "")
        games = db.list_games(keyword=q, only_active=True)
        if tag:
            games = [x for x in games if tag in x.tags]
        return render_template("browse.html", games=games, q=q, tag=tag)

    # ------------------------------------------------------------ 平板 API（JSON）
    def api_json() -> dict:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            abort(400, "請用 JSON 物件傳送資料（Content-Type: application/json）")
        return data

    def game_json(r) -> dict:
        x: BoardGame = r.game
        if x.youtube_url:
            yt_url, yt_search = x.youtube_url, bool(x.youtube_is_search)
            vid = None if yt_search else extract_video_id(x.youtube_url)
            if vid is None:
                yt_search = yt_search or "results?search_query" in yt_url
            yt_title = x.youtube_title or ("在 YouTube 搜尋教學" if yt_search else "教學影片")
        else:
            q = f"{x.name} 桌遊 教學"
            yt_url, yt_search, vid, yt_title = search_page_url(q), True, None, f"在 YouTube 搜尋「{q}」"
        return {
            "id": x.id, "name": x.name, "name_en": x.name_en,
            "players_text": x.players_text, "time_text": x.time_text, "weight_text": x.weight_text,
            "min_age": x.min_age, "shelf": x.shelf,
            "price": (round(x.price) if x.price else 0),
            "in_stock": x.stock > 0,
            "tags": x.tag_labels, "description": x.description, "image_url": x.image_url,
            "match_percent": r.match_percent, "reasons": list(r.reasons),
            "played_before": bool(r.played_before),
            "youtube": {"url": yt_url, "video_id": vid, "is_search": bool(yt_search), "title": yt_title},
        }

    @app.route("/api/v1/ping")
    def api_ping():
        return jsonify({"ok": True, "store_name": g.settings["store_name"], "version": API_VERSION,
                        "device_name": g.device["name"]})

    @app.route("/api/v1/config")
    def api_config():
        S = g.settings
        return jsonify({"ok": True, "store_name": S["store_name"], "top_n": S["top_n"],
                        "allow_member": S["allow_member"],
                        "points_per_quiz": S["points_per_quiz"] if S["points_daily_limit"] > 0 else 0,
                        "show_price": S["show_price"], "questions": quiz().public_questions()})

    @app.route("/api/v1/member/lookup", methods=["POST"])
    def api_member_lookup():
        if not g.settings["allow_member"]:
            return api_error(403, "目前未開放會員功能")
        data = api_json()
        if not lookup_allowed(f"dev:{g.device['id']}"):
            return api_error(429, "查詢太頻繁，請稍後再試")
        m = find_member_by_key(data.get("member_key"))
        if m is None:
            return jsonify({"ok": False, "message": "查不到這個會員，可以先略過或洽櫃檯",
                            "error": "member_not_found"})
        return jsonify({"ok": True, "member_no": m.member_no, "greeting": greeting_of(m),
                        "points": m.app_points})

    @app.route("/api/v1/recommend", methods=["POST"])
    def api_recommend():
        data = api_json()
        answers = data.get("answers")
        if not isinstance(answers, dict):
            return api_error(400, "缺少 answers")
        member = None
        member_no = data.get("member_no")
        if member_no and g.settings["allow_member"]:
            member = db.get_member_by_no(str(member_no).strip()[:40])
        try:
            recs, excluded, prof = run_recommend(answers, member)
        except ValueError as e:
            return api_error(400, str(e))
        clean = {q.key: answers.get(q.key) for q in quiz().questions}
        log_id = db.add_quiz_log(clean, [r.game.id for r in recs],
                                 member_no=member.member_no if member else "", device_id=g.device["id"])
        return jsonify({
            "ok": True, "log_id": log_id, "results": [game_json(r) for r in recs],
            "member": None if member is None else {
                "greeting": greeting_of(member), "excluded_count": excluded,
                "personalized": bool(prof and prof.has_history)},
        })

    @app.route("/api/v1/quiz/<int:log_id>/claim", methods=["POST"])
    def api_claim(log_id: int):
        if not g.settings["allow_member"]:
            return api_error(403, "目前未開放會員功能")
        data = api_json()
        member_no = str(data.get("member_no") or "").strip()[:40]
        m = db.get_member_by_no(member_no) if member_no else None
        if m is None:
            return api_error(404, "查不到這個會員")
        log = db.get_quiz_log(log_id)
        if log is None or log["device_id"] != g.device["id"]:
            return api_error(404, "找不到這次推薦紀錄")
        ok, added, total, msg = db.claim_quiz_points(
            log_id, m.member_no, g.settings["points_per_quiz"], g.settings["points_daily_limit"],
            device_id=g.device["id"])
        if not ok:
            return api_error(409, msg)
        return jsonify({"ok": True, "message": msg, "points_added": added, "total_points": total})

    # ------------------------------------------------------------ 後台：登入
    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        if request.method == "POST":
            pw = request.form.get("password", "")
            if check_password_hash(db.get_setting("admin_password_hash") or "", pw):
                session["admin"] = True
                return redirect(safe_next(request.args.get("next"), url_for("admin_dashboard")))
            flash("密碼錯誤", "error")
        return render_template("admin/login.html")

    @app.route("/admin/logout")
    def admin_logout():
        session.pop("admin", None)
        return redirect(url_for("index"))

    # ------------------------------------------------------------ 後台：總覽
    @app.route("/admin")
    @admin_required
    def admin_dashboard():
        logs = db.list_quiz_logs(limit=10)
        names = {x.id: x.name for x in db.list_games()}
        for lg in logs:
            lg["summary"] = summarize(lg["answers"])
            lg["games"] = [names.get(i, f"#{i}") for i in lg["result_ids"][:3]]
        return render_template("admin/dashboard.html", counts=db.count_games(),
                               member_count=db.count_members(), top=db.top_recommended(10),
                               logs=logs, pw_default=db.get_setting("password_is_default", False),
                               pos=POSConfig.load(db), devices=db.count_devices())

    # ------------------------------------------------------------ 後台：桌遊
    @app.route("/admin/games")
    @admin_required
    def admin_games():
        q = request.args.get("q", "").strip()
        missing = request.args.get("missing") == "1"
        return render_template("admin/games.html",
                               games=db.list_games(keyword=q, missing_youtube=missing),
                               q=q, missing=missing)

    def _game_from_form(game: BoardGame) -> BoardGame:
        f = request.form

        def num(name, cast, default):
            try:
                v = float(str(f.get(name, default)).strip())
            except (TypeError, ValueError):
                return default
            if not math.isfinite(v):
                return default
            return cast(v)
        game.name = f.get("name", "").strip()
        game.name_en = f.get("name_en", "").strip()
        game.min_players = num("min_players", int, 2)
        game.max_players = max(game.min_players, num("max_players", int, 4))
        game.min_time = num("min_time", int, 30)
        game.max_time = max(game.min_time, num("max_time", int, 60))
        game.weight = min(5.0, max(1.0, num("weight", float, 2.0)))
        game.min_age = num("min_age", int, 8)
        game.tags = normalize_tags(f.getlist("tags"))
        game.description = f.get("description", "").strip()
        game.pos_sku = f.get("pos_sku", "").strip()
        game.price = num("price", float, 0.0)
        game.stock = num("stock", int, 0)
        game.rentable = f.get("rentable") == "1"
        game.shelf = f.get("shelf", "").strip()
        new_yt = f.get("youtube_url", "").strip()
        if new_yt != game.youtube_url:
            game.youtube_url = new_yt
            game.youtube_title = f.get("youtube_title", "").strip() or ("手動設定" if new_yt else "")
            game.youtube_is_search = "results?search_query" in new_yt
        game.image_url = f.get("image_url", "").strip()
        game.active = f.get("active") == "1"
        return game

    @app.route("/admin/games/new", methods=["GET", "POST"])
    @app.route("/admin/games/<int:game_id>/edit", methods=["GET", "POST"])
    @admin_required
    def admin_game_edit(game_id: int | None = None):
        game = db.get_game(game_id) if game_id else BoardGame(name="")
        if game is None:
            abort(404)
        if request.method == "POST":
            game = _game_from_form(game)
            if not game.name:
                flash("請輸入遊戲名稱", "error")
            else:
                db.save_game(game)
                flash(f"已儲存「{game.name}」", "ok")
                return redirect(url_for("admin_games"))
        return render_template("admin/game_edit.html", game=game)

    @app.route("/admin/games/<int:game_id>/delete", methods=["POST"])
    @admin_required
    def admin_game_delete(game_id: int):
        game = db.get_game(game_id)
        if game:
            db.delete_game(game_id)
            flash(f"已刪除「{game.name}」", "ok")
        return redirect(url_for("admin_games"))

    @app.route("/admin/games/<int:game_id>/youtube", methods=["POST"])
    @admin_required
    def admin_game_youtube(game_id: int):
        game = db.get_game(game_id)
        if not game:
            abort(404)
        try:
            v = youtube_finder().find(game)
            db.update_youtube(game.id, v.url, v.title, v.is_search)
            flash(f"「{game.name}」→ {v.title}", "ok" if not v.is_search else "warn")
        except Exception as e:
            flash(f"搜尋失敗：{e}", "error")
        return redirect(safe_next(request.form.get("back"), url_for("admin_games")))

    # ------------------------------------------------------------ 後台：YouTube 批次
    @app.route("/admin/youtube", methods=["GET", "POST"])
    @admin_required
    def admin_youtube():
        if request.method == "POST":
            action = request.form.get("action")
            if action == "save_key":
                db.set_setting("youtube_api_key", request.form.get("api_key", "").strip())
                flash("已儲存 YouTube API 金鑰", "ok")
            elif action == "batch":
                limit = to_int(request.form.get("limit"), 20, 1, 100)
                finder = youtube_finder()
                targets = db.list_games(missing_youtube=True)
                if not finder.api_key:
                    targets = [x for x in targets if not x.youtube_url]
                done = found = 0
                errors = []
                for game in targets[:limit]:
                    try:
                        v = finder.find(game)
                        db.update_youtube(game.id, v.url, v.title, v.is_search)
                        done += 1
                        found += 0 if v.is_search else 1
                    except Exception as e:
                        errors.append(f"{game.name}：{e}")
                        if "quota" in str(e).lower():
                            break
                flash(f"處理 {done} 款，找到教學影片 {found} 款", "ok")
                for err in errors[:5]:
                    flash(err, "error")
            return redirect(url_for("admin_youtube"))
        missing = db.list_games(missing_youtube=True)
        return render_template("admin/youtube.html", missing=missing, counts=db.count_games())

    # ------------------------------------------------------------ 後台：匯入匯出
    @app.route("/admin/import", methods=["GET", "POST"])
    @admin_required
    def admin_import():
        if request.method == "POST":
            kind = request.form.get("kind", "games")
            if kind not in ("games", "members", "history"):
                abort(400, "未知的匯入類型")
            f = request.files.get("file")
            if not f or not f.filename:
                flash("請選擇檔案", "error")
                return redirect(url_for("admin_import"))
            try:
                data = f.read()
                if kind == "history":
                    dk = "rent" if request.form.get("default_kind") == "rent" else "buy"
                    res = HistoryImporter(db).import_rows(TableReader.read(f.filename, data), default_kind=dk)
                else:
                    importer = GameImporter(db) if kind == "games" else MemberImporter(db)
                    res = importer.import_file(f.filename, data)
                label = {"games": "桌遊", "members": "會員", "history": "銷售／租借紀錄"}[kind]
                flash(f"{label}匯入完成：{res.summary()}", "ok" if not res.errors else "warn")
                for err in res.errors[:10]:
                    flash(err, "error")
            except Exception as e:
                flash(f"匯入失敗：{e}", "error")
            return redirect(url_for("admin_import"))
        return render_template("admin/import.html")

    @app.route("/admin/export/games.csv")
    @admin_required
    def admin_export_games():
        return Response(GameImporter(db).export_csv(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=boardgames.csv"})

    @app.route("/admin/template/<kind>.csv")
    @admin_required
    def admin_template(kind: str):
        if kind == "games":
            text = ("遊戲名稱,英文名稱,人數,時間,難度,年齡,類型,商品編號,售價,庫存,可租借,櫃位,介紹,教學影片\n"
                    "璀璨寶石,Splendor,2-4,30,1.8,10,策略、卡牌、家庭,BG0001,1350,3,是,A-1,收集寶石換發展卡,\n")
        elif kind == "members":
            text = "會員編號,姓名,手機,等級,點數\nM0001,王小明,0912345678,一般,120\n"
        elif kind == "history":
            text = ("會員編號,商品編號,類型,日期\nM0001,BG0003,購買,2026-01-15\n"
                    "M0001,BG0012,租借,2026-02-02 19:30\n")
        else:
            abort(404)
        return Response(text.encode("utf-8-sig"), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename={kind}_template.csv"})

    # ------------------------------------------------------------ 後台：POS
    GAME_MAP_FIELDS = [("name", "遊戲名稱 *"), ("pos_sku", "商品編號"), ("price", "售價"),
                       ("stock", "庫存"), ("min_players", "最少人數"), ("max_players", "最多人數"),
                       ("min_time", "最短時間"), ("max_time", "最長時間"), ("weight", "難度"),
                       ("min_age", "年齡"), ("tags", "類型標籤"), ("description", "介紹"),
                       ("active", "上架中")]
    MEMBER_MAP_FIELDS = [("member_no", "會員編號 *"), ("name", "姓名"), ("phone", "手機"),
                         ("level", "等級"), ("points", "點數")]
    HISTORY_MAP_FIELDS = [("member_no", "會員編號 *"), ("pos_sku", "商品編號 *"),
                          ("kind", "類型（購買/租借）"), ("occurred_at", "交易時間")]

    @app.route("/admin/pos", methods=["GET", "POST"])
    @admin_required
    def admin_pos():
        cfg = POSConfig.load(db)
        preview = None
        if request.method == "POST":
            f = request.form
            action = f.get("action")
            new_url = f.get("url", "").strip()
            if "****" in new_url:
                # 畫面上顯示的是遮罩後的字串：把原本的密碼放回去（使用者可能只改了主機或資料庫名）
                old_pw = cfg.password
                if old_pw is not None:
                    cfg.url = new_url.replace("****", old_pw, 1)
            else:
                cfg.url = new_url
            cfg.game_query = f.get("game_query", "").strip() or cfg.game_query
            cfg.member_query = f.get("member_query", "").strip() or cfg.member_query
            cfg.game_mapping = {k: f.get(f"gm_{k}", "").strip() for k, _ in GAME_MAP_FIELDS}
            cfg.member_mapping = {k: f.get(f"mm_{k}", "").strip() for k, _ in MEMBER_MAP_FIELDS}
            cfg.history_query = f.get("history_query", "").strip() or cfg.history_query
            cfg.history_mapping = {k: f.get(f"hm_{k}", "").strip() for k, _ in HISTORY_MAP_FIELDS}
            cfg.history_default_kind = "rent" if f.get("history_default_kind") == "rent" else "buy"
            cfg.sync_games = f.get("sync_games") == "1"
            cfg.sync_members = f.get("sync_members") == "1"
            cfg.sync_history = f.get("sync_history") == "1"
            cfg.save(db)
            conn = POSConnector(cfg)
            try:
                if action == "test":
                    flash(conn.test_connection(), "ok")
                elif action in ("preview_games", "preview_members", "preview_history"):
                    which = action.split("_", 1)[1]
                    rows = conn.preview(which)
                    preview = {"title": {"games": "桌遊", "members": "會員", "history": "銷售／租借紀錄"}[which],
                               "rows": rows, "cols": list(rows[0].keys()) if rows else []}
                    if not rows:
                        flash("查詢成功，但沒有資料", "warn")
                elif action == "sync":
                    results = conn.sync(db)
                    if not results:
                        flash("沒有勾選任何要同步的項目", "warn")
                    for k, r in results.items():
                        label = {"games": "桌遊", "members": "會員", "history": "銷售／租借紀錄"}[k]
                        flash(f"{label}同步：{r.summary()}", "ok" if not r.errors else "warn")
                        for err in r.errors[:5]:
                            flash(err, "error")
                    db.set_setting("pos_last_sync", datetime.now().strftime("%Y-%m-%d %H:%M"))
                else:
                    flash("已儲存 POS 設定", "ok")
            except Exception as e:
                flash(f"POS 操作失敗：{e}", "error")
            if preview is None:
                return redirect(url_for("admin_pos"))
        return render_template("admin/pos.html", cfg=cfg, preview=preview,
                               game_fields=GAME_MAP_FIELDS, member_fields=MEMBER_MAP_FIELDS,
                               history_fields=HISTORY_MAP_FIELDS,
                               last_sync=db.get_setting("pos_last_sync", ""))

    # ------------------------------------------------------------ 後台：會員
    @app.route("/admin/members")
    @admin_required
    def admin_members():
        q = request.args.get("q", "").strip()
        return render_template("admin/members.html", members=db.list_members(keyword=q), q=q,
                               total=db.count_members())

    @app.route("/admin/members/<path:member_no>", methods=["GET", "POST"])
    @admin_required
    def admin_member_detail(member_no: str):
        m = db.get_member_by_no(member_no)
        if not m:
            abort(404)
        if request.method == "POST":
            action = request.form.get("action")
            amount = to_int(request.form.get("amount"), 0, 0, 1_000_000)
            reason = (request.form.get("reason") or "").strip()
            if action not in ("add", "redeem"):
                abort(400, "未知的操作")
            if amount <= 0:
                flash("請輸入大於 0 的點數", "error")
            else:
                try:
                    new = db.adjust_points(m.member_no, amount if action == "add" else -amount,
                                           reason if action == "add" else f"兌換：{reason}" if reason else "")
                    flash(f"已{'加' if action == 'add' else '扣'} {amount} 點，目前 {new} 點", "ok")
                except ValueError as e:
                    flash(str(e), "error")
            return redirect(url_for("admin_member_detail", member_no=m.member_no))
        logs = db.list_quiz_logs(member_no=m.member_no)
        names = {x.id: x.name for x in db.list_games()}
        for lg in logs:
            lg["summary"] = summarize(lg["answers"])
            lg["games"] = [names.get(i, f"#{i}") for i in lg["result_ids"]]
        return render_template("admin/member_detail.html", m=m, logs=logs,
                               ledger=db.list_points(m.member_no), history=db.list_history(m.member_no))

    # ------------------------------------------------------------ 後台：紀錄
    @app.route("/admin/logs")
    @admin_required
    def admin_logs():
        logs = db.list_quiz_logs(limit=300)
        names = {x.id: x.name for x in db.list_games()}
        for lg in logs:
            lg["summary"] = summarize(lg["answers"])
            lg["games"] = [names.get(i, f"#{i}") for i in lg["result_ids"]]
        devices = {d["id"]: d["name"] for d in db.list_devices()}
        return render_template("admin/logs.html", logs=logs, devices=devices)

    # ------------------------------------------------------------ 後台：設定
    @app.route("/admin/settings", methods=["GET", "POST"])
    @admin_required
    def admin_settings():
        if request.method == "POST":
            f = request.form
            if f.get("action") == "password":
                cur, new, new2 = f.get("current", ""), f.get("new", ""), f.get("new2", "")
                if not check_password_hash(db.get_setting("admin_password_hash"), cur):
                    flash("目前密碼錯誤", "error")
                elif len(new) < 6:
                    flash("新密碼至少 6 碼", "error")
                elif new != new2:
                    flash("兩次輸入的新密碼不同", "error")
                else:
                    db.set_setting("admin_password_hash", generate_password_hash(new))
                    db.set_setting("password_is_default", False)
                    flash("密碼已更新", "ok")
            else:
                db.set_setting("store_name", f.get("store_name", "").strip() or "桌遊小幫手")
                db.set_setting("top_n", to_int(f.get("top_n"), g.settings["top_n"], 3, 10))
                db.set_setting("allow_member", f.get("allow_member") == "1")
                db.set_setting("show_price", f.get("show_price") == "1")
                db.set_setting("points_per_quiz",
                               to_int(f.get("points_per_quiz"), g.settings["points_per_quiz"], 0, 100000))
                db.set_setting("points_daily_limit",
                               to_int(f.get("points_daily_limit"), g.settings["points_daily_limit"], 0, 100))
                flash("設定已儲存", "ok")
            return redirect(url_for("admin_settings"))
        return render_template("admin/settings.html")

    # ------------------------------------------------------------ 後台：題目設定
    @app.route("/admin/quiz", methods=["GET", "POST"])
    @admin_required
    def admin_quiz():
        text = None
        if request.method == "POST":
            action = request.form.get("action")
            if action == "reset":
                db.set_setting(QUIZ_SETTING_KEY, None)     # 清掉自訂 → 之後預設題目更新也會跟著用
                flash("已還原成預設題目", "ok")
                return redirect(url_for("admin_quiz"))
            text = request.form.get("quiz_json", "")
            try:
                clean = parse_quiz_json(text)
                QuizConfig.from_dict(clean)
                db.set_setting(QUIZ_SETTING_KEY, clean)
                flash("題目設定已儲存，前台與平板下次載入就會使用新題目", "ok")
                return redirect(url_for("admin_quiz"))
            except ValueError as e:
                flash(f"沒有儲存：{e}", "error")
        cfg = quiz()
        return render_template("admin/quiz.html", cfg=cfg, text=text if text is not None else cfg.to_json(),
                               is_custom=isinstance(db.get_setting(QUIZ_SETTING_KEY), dict))

    # ------------------------------------------------------------ 後台：平板配對
    @app.route("/admin/devices", methods=["GET", "POST"])
    @admin_required
    def admin_devices():
        if request.method == "POST":
            action = request.form.get("action")
            dev_id = to_int(request.form.get("device_id"), 0)
            if action == "add":
                name = (request.form.get("name") or "").strip()[:40] or "平板"
                key = secrets.token_urlsafe(18)
                new_id = db.add_device(name, key)
                session["new_device"] = new_id
                flash(f"已新增裝置「{name}」，請把下方網址與金鑰輸入平板", "ok")
            elif action in ("disable", "enable"):
                db.set_device_active(dev_id, action == "enable")
                flash("已停用裝置" if action == "disable" else "已重新啟用裝置", "ok")
            elif action == "delete":
                db.delete_device(dev_id)
                flash("已刪除裝置，該平板需要重新配對", "ok")
            else:
                abort(400, "未知的操作")
            return redirect(url_for("admin_devices"))
        host = request.host or ""
        port = to_int(host.rsplit(":", 1)[1], 5000, 1, 65535) \
            if ":" in host and not host.endswith("]") else (443 if request.scheme == "https" else 80)
        server_url = f"http://{local_ip()}:{port}"
        return render_template("admin/devices.html", devices=db.list_devices(), server_url=server_url,
                               new_device=session.pop("new_device", None))

    def _err(code: int, message: str):
        if is_api():
            return api_error(code, message)
        return render_template("error.html", code=code, message=message), code

    @app.errorhandler(404)
    def _404(e):
        return _err(404, "找不到這個頁面" if not is_api() else "找不到這個 API")

    @app.errorhandler(400)
    def _400(e):
        return _err(400, getattr(e, "description", None) or "請求錯誤")

    @app.errorhandler(413)
    def _413(e):
        mb = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
        return _err(413, f"檔案太大（上限 {mb} MB）")

    @app.errorhandler(HTTPException)
    def _http(e):
        return _err(e.code or 500, e.name)

    @app.errorhandler(Exception)
    def _500(e):
        if isinstance(e, HTTPException):
            return _http(e)
        app.logger.exception("Unhandled error")
        return _err(500, "系統發生錯誤，請稍後再試或洽店員")

    return app


def local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


if __name__ == "__main__":
    # Windows 舊主控台（cp950）印不出的字元改成 ?，避免啟動時就 UnicodeEncodeError
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    port = to_int(os.environ.get("BGR_PORT"), 5000, 1, 65535)
    app = create_app()
    db: Database = app.config["DB"]
    if db.count_games()["total"] == 0:
        sample = Path(__file__).resolve().parent / "sample_data" / "games_sample.csv"
        if sample.exists():
            r = GameImporter(db).import_file(sample.name, sample.read_bytes())
            print(f"[首次啟動] 已匯入範例桌遊：{r.summary()}")
    ip = local_ip()
    print("=" * 56)
    print(f" 桌遊推薦 APP v{API_VERSION} 已啟動")
    print(f"  前台（客人作答）：http://{ip}:{port}/")
    print(f"  後台（店員管理）：http://{ip}:{port}/admin")
    print(f"  平板 APP 伺服器網址：http://{ip}:{port}（金鑰請到後台「平板配對」產生）")
    if db.get_setting("password_is_default", False):
        print(f"  預設後台密碼：{DEFAULT_PASSWORD}（登入後請立即修改）")
    print("  關閉本視窗即停止服務")
    print("=" * 56)
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8)
    except ImportError:
        app.run(host="0.0.0.0", port=port, debug=False)
