"""第 2 版功能測試：題目設定、會員紀錄排除／個人化、點數、平板 API、POS 銷售紀錄、舊資料庫遷移。"""
import copy
import io
import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from core.database import Database  # noqa: E402
from core.importer import GameImporter, HistoryImporter, MemberImporter  # noqa: E402
from core.models import Member  # noqa: E402
from core.pos_connector import POSConfig, POSConnector  # noqa: E402
from core.quiz import QuizConfig, parse_quiz_json, validate_quiz  # noqa: E402
from core.recommender import MemberProfile, PLAYED_REASON, Recommender  # noqa: E402

SAMPLE = ROOT / "sample_data" / "games_sample.csv"
OWL = dict(players="3-4", time="epic", animal="owl", snack="hotpot", phrase="think")


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "t.db")
    GameImporter(d).import_file(SAMPLE.name, SAMPLE.read_bytes())
    return d


def gid(db, sku):
    return db.find_game_by_sku_or_name(sku, "").id


# ---------------- 題目設定 ----------------
def test_default_quiz_shape():
    cfg = QuizConfig.default()
    assert [q.key for q in cfg.questions] == ["players", "time", "animal", "snack", "phrase"]
    hen = cfg.question("animal").option("hen")
    assert hen.kid and "family" in hen.tags and hen.emoji == "🐣"
    assert cfg.question("snack").option("hotpot").max_weight is None
    assert sum(q.weight for q in cfg.questions) + cfg.stock_weight == 100


def test_quiz_validation_rejects_bad_config():
    base = QuizConfig.default_dict()
    bad_cases = []
    c = copy.deepcopy(base); c["questions"][2]["options"][0]["tags"] = {"nope": 1}; bad_cases.append(c)
    c = copy.deepcopy(base); c["questions"][2]["options"][1]["value"] = "dog"; bad_cases.append(c)
    c = copy.deepcopy(base); c["questions"] = c["questions"][1:]; bad_cases.append(c)          # 沒有 players
    c = copy.deepcopy(base); c["questions"][3]["options"][0]["target"] = 9; bad_cases.append(c)
    c = copy.deepcopy(base); c["questions"][1]["weight"] = "25"; bad_cases.append(c)
    c = copy.deepcopy(base); c["questions"][2]["options"][0]["evil"] = 1; bad_cases.append(c)
    c = copy.deepcopy(base); c["questions"][2]["key"] = "Bad Key"; bad_cases.append(c)
    c = copy.deepcopy(base); c["questions"][0]["options"][0]["min"] = 5; bad_cases.append(c)   # min > max
    c = copy.deepcopy(base); c["questions"][2]["options"][4]["kid"] = "yes"; bad_cases.append(c)
    for c in bad_cases:
        with pytest.raises(ValueError):
            validate_quiz(c)
    with pytest.raises(ValueError):
        parse_quiz_json("{not json")
    assert validate_quiz(base)["questions"][0]["key"] == "players"


def test_custom_quiz_drives_recommender(db):
    data = QuizConfig.default_dict()
    data["questions"][2]["options"][0]["tags"] = {"coop": 1.0}     # 把狗狗改成合作
    cfg = QuizConfig.from_dict(data)
    recs = Recommender(db.list_games(), cfg).recommend(
        dict(players="3-4", time="medium", animal="dog", snack="chicken", phrase="thanks"))
    assert all("coop" in r.game.tags for r in recs[:3])


def test_broken_quiz_setting_falls_back_to_default(db):
    db.set_setting("quiz_config", {"questions": "壞掉"})
    assert QuizConfig.load(db).question("animal") is not None


def test_natural_reasons(db):
    recs = Recommender(db.list_games()).recommend(
        dict(players="3-4", time="medium", animal="bee", snack="chicken", phrase="thanks"))
    text = " ".join(recs[0].reasons)
    assert "符合『團結蜜蜂』的合作氣氛" in text and "難度像鹹酥雞：輕中度" in text


def test_two_players_owl_prefers_duo(db):
    for t in ("short", "medium"):
        for snack in ("chicken", "dessert"):
            recs = Recommender(db.list_games()).recommend(
                dict(players="2", time=t, animal="owl", snack=snack, phrase="think"))
            assert recs[0].game.max_players == 2, (t, snack, [r.game.name for r in recs])
            duo = [r for r in recs[:3] if r.game.max_players == 2]
            if t == "short":      # 範例資料的兩人遊戲都在 30 分鐘內
                assert len(duo) >= 2, (t, snack, [r.game.name for r in recs])
            assert any("兩人專屬" in x for x in duo[0].reasons)


# ---------------- 會員紀錄：排除、補位、個人化 ----------------
def test_history_excludes_played_games(db):
    base = Recommender(db.list_games()).recommend(OWL)
    top_ids = [r.game.id for r in base[:2]]
    prof = MemberProfile(played_ids=set(top_ids), counts={i: 1 for i in top_ids},
                         history=[db.get_game(i) for i in top_ids])
    rec = Recommender(db.list_games())
    recs = rec.recommend(OWL, profile=prof)
    assert not set(top_ids) & {r.game.id for r in recs}
    assert rec.last_excluded == 2 and len(recs) == 5


def test_history_fills_with_played_when_not_enough(tmp_path):
    d = Database(tmp_path / "f.db")
    from core.models import BoardGame
    ids = [d.save_game(BoardGame(name=f"G{i}", min_players=2, max_players=4, tags=["strategy"])) for i in range(4)]
    prof = MemberProfile(played_ids={ids[0], ids[1]}, counts={ids[0]: 1, ids[1]: 1},
                         history=[d.get_game(ids[0]), d.get_game(ids[1])])
    recs = Recommender(d.list_games()).recommend(OWL, top_n=3, profile=prof)
    assert len(recs) == 3
    assert [r.played_before for r in recs] == [False, False, True]
    assert recs[2].reasons[0] == PLAYED_REASON


def test_personalized_bonus(db):
    catan = db.find_game_by_sku_or_name("BG0003", "")
    stone = db.find_game_by_sku_or_name("", "石器時代")
    a = dict(players="3-4", time="long", animal="dog", snack="chicken", phrase="comeback")
    plain = {r.game.id: r for r in Recommender(db.list_games()).recommend(a, top_n=40)}
    prof = MemberProfile(played_ids={catan.id}, counts={catan.id: 3}, history=[catan])
    pers = {r.game.id: r for r in Recommender(db.list_games()).recommend(a, top_n=40, profile=prof)}
    diff = pers[stone.id].score - plain[stone.id].score
    assert 4 <= diff <= 10.0001
    assert "和你常玩的《卡坦島》風格相近" in pers[stone.id].reasons
    assert all(pers[i].score - plain[i].score <= 10.0001 for i in pers if i in plain)


def test_history_import_and_dedupe(db):
    MemberImporter(db).import_rows([{"會員編號": "M1", "姓名": "王小明"}])
    csv = ("會員編號,商品編號,類型,日期\nM1,BG0003,購買,2026-01-01\nM1,BG0003,購買,2026-01-01\n"
           "M1,BG0012,租借,2026-02-01\nM1,ZZZ,購買,2026-03-01\nM1,BG0001,怪怪,2026-03-01\n").encode()
    r = HistoryImporter(db).import_file("h.csv", csv)
    assert r.inserted == 3 and r.skipped == 2
    assert any("找不到對應" in e for e in r.errors) and any("交易類型" in e for e in r.errors)
    counts = db.history_game_counts("M1")
    assert set(counts) == {gid(db, "BG0003"), gid(db, "BG0012")}
    # 之後才補上商品編號的桌遊也能對上
    g = db.find_game_by_sku_or_name("", "UNO")
    g.pos_sku = "ZZZ"
    db.save_game(g)
    assert g.id in db.history_game_counts("M1")
    # 再匯入一次不會重複
    assert HistoryImporter(db).import_file("h.csv", csv).inserted == 0


# ---------------- 點數 ----------------
def test_points_daily_limit_and_no_negative(db):
    db.upsert_member(Member(member_no="M1", name="王小明"))
    logs = [db.add_quiz_log({"a": 1}, [1]) for _ in range(3)]
    ok, added, total, _ = db.claim_quiz_points(logs[0], "M1", 10, 1)
    assert ok and added == 10 and total == 10
    ok, added, total, msg = db.claim_quiz_points(logs[1], "M1", 10, 1)
    assert ok and added == 0 and total == 10 and "每日限" in msg
    ok, *_ = db.claim_quiz_points(logs[0], "M1", 10, 1)      # 重複領
    assert not ok
    assert db.claim_quiz_points(logs[2], "M1", 0, 1)[1] == 0  # 0 表示不送
    with pytest.raises(ValueError):
        db.adjust_points("M1", -11, "兌換飲料")
    assert db.adjust_points("M1", -10, "兌換飲料") == 0
    with pytest.raises(ValueError):
        db.adjust_points("M1", 5, "")                         # 沒原因
    assert db.adjust_points("M1", 5, "活動") == 5
    assert [p["delta"] for p in db.list_points("M1")] == [5, -10, 10]
    assert db.get_member_by_no("M1").app_points == 5


# ---------------- 舊資料庫遷移 ----------------
def test_old_database_migration(tmp_path):
    p = tmp_path / "old.db"
    c = sqlite3.connect(p)
    c.executescript("""
      CREATE TABLE members (id INTEGER PRIMARY KEY AUTOINCREMENT, member_no TEXT UNIQUE NOT NULL, name TEXT DEFAULT '',
        phone TEXT DEFAULT '', level TEXT DEFAULT '', points INTEGER DEFAULT 0, source TEXT DEFAULT 'manual', updated_at TEXT);
      CREATE TABLE quiz_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, answers TEXT, result_ids TEXT,
        member_no TEXT DEFAULT '');
      INSERT INTO members (member_no, name, points) VALUES ('OLD1', '舊會員', 80);
      INSERT INTO quiz_logs (created_at, answers, result_ids, member_no) VALUES ('2025-01-01 10:00:00',
        '{"players":"2","level":"new","mood":"party"}', '1,2', 'OLD1');
      INSERT INTO quiz_logs (created_at, answers, result_ids, member_no) VALUES ('2025-01-01 11:00:00', '{}', '', '');
    """)
    c.commit()
    c.close()
    d = Database(p)
    m = d.get_member_by_no("OLD1")
    assert m.app_points == 0 and m.points == 80
    assert d.get_quiz_log(1)["claimed"] is True        # 舊版已綁會員 → 視為已領
    assert d.get_quiz_log(2)["claimed"] is False
    assert d.count_devices() == {"total": 0, "active": 0}
    Database(p)                                         # 第二次開啟不會重複 ALTER
    # 舊答案仍可在後台顯示
    app = create_app(p)
    c = app.test_client()
    tok = re.search(r'name="_csrf" value="([^"]+)"', c.get("/").get_data(as_text=True)).group(1)
    c.post("/admin/login", data={"_csrf": tok, "password": "admin1234"})
    for path in ["/admin", "/admin/logs", "/admin/members/OLD1"]:
        assert c.get(path).status_code == 200, path


# ---------------- POS 銷售紀錄同步 ----------------
def test_pos_history_sync(db, tmp_path):
    p = tmp_path / "pos.db"
    c = sqlite3.connect(p)
    c.executescript("""
      CREATE TABLE vip (card_no TEXT, cname TEXT, mobile TEXT);
      INSERT INTO vip VALUES ('V1','林小華','0922000111');
      CREATE TABLE sales (card TEXT, item TEXT, typ TEXT, dt TEXT);
      INSERT INTO sales VALUES ('V1','BG0003','S','2026-01-01 12:00');
      INSERT INTO sales VALUES ('V1','BG0025','R','2026-01-02 12:00');
      INSERT INTO sales VALUES ('V1','DRK01','S','2026-01-02 12:00');
      CREATE TABLE sales2 (card TEXT, item TEXT, dt TEXT);
      INSERT INTO sales2 VALUES ('V1','BG0001','2026-01-03');
    """)
    c.commit()
    c.close()
    cfg = POSConfig(url=f"sqlite:///{p}", sync_games=False,
                    member_query="SELECT * FROM vip",
                    member_mapping={"member_no": "card_no", "name": "cname", "phone": "mobile"},
                    sync_history=True, history_query="SELECT * FROM sales WHERE dt >= '2025-01-01'",
                    history_mapping={"member_no": "card", "pos_sku": "item", "kind": "typ", "occurred_at": "dt"})
    res = POSConnector(cfg).sync(db)
    assert res["history"].inserted == 3 and "games" not in res
    hist = {h["pos_sku"]: h for h in db.list_history("V1")}
    assert hist["BG0003"]["kind"] == "buy" and hist["BG0025"]["kind"] == "rent"
    assert hist["BG0003"]["game_name"] == "卡坦島"
    assert POSConnector(cfg).sync(db)["history"].inserted == 0          # 重複同步不會重複
    # 沒有 kind 欄 → 用預設
    cfg2 = POSConfig(url=f"sqlite:///{p}", sync_games=False, sync_members=False, sync_history=True,
                     history_query="SELECT * FROM sales2", history_default_kind="rent",
                     history_mapping={"member_no": "card", "pos_sku": "item", "occurred_at": "dt"})
    POSConnector(cfg2).sync(db)
    assert {h["pos_sku"]: h["kind"] for h in db.list_history("V1")}["BG0001"] == "rent"
    # 查詢黑名單仍然有效
    cfg2.history_query = "SELECT * FROM sales; DROP TABLE sales"
    with pytest.raises(ValueError):
        POSConnector(cfg2).sync(db)
    assert POSConfig.load(db).sync_history is False        # 預設不同步


# ---------------- 平板 API ----------------
@pytest.fixture
def api(tmp_path):
    app = create_app(tmp_path / "api.db")
    d = app.config["DB"]
    GameImporter(d).import_file(SAMPLE.name, SAMPLE.read_bytes())
    d.upsert_member(Member(member_no="M1", name="王小明", phone="0912345678"))
    d.add_device("平板A", "KEY_A_123456789012345")
    d.add_device("平板B", "KEY_B_123456789012345")
    app.config["TESTING"] = True
    c = app.test_client()

    def call(method, path, key="KEY_A_123456789012345", **kw):
        headers = {"X-Device-Key": key} if key else {}
        return getattr(c, method)(path, headers=headers, **kw)
    return call, d, c


def test_api_requires_device_key(api):
    call, d, c = api
    for key in (None, "", "wrong"):
        r = call("get", "/api/v1/ping", key=key)
        assert r.status_code == 401 and r.is_json and r.get_json()["ok"] is False and r.get_json()["error"]
    r = call("post", "/api/v1/recommend", key="wrong", json={})
    assert r.status_code == 401 and r.is_json
    # 停用後失效
    dev = d.get_device_by_key("KEY_B_123456789012345")
    d.set_device_active(dev["id"], False)
    assert call("get", "/api/v1/ping", key="KEY_B_123456789012345").status_code == 401
    # 正確金鑰 → 更新 last_seen
    r = call("get", "/api/v1/ping")
    assert r.status_code == 200 and r.get_json() == {"ok": True, "store_name": "桌遊小幫手", "version": "2.0",
                                                     "device_name": "平板A"}
    assert d.get_device_by_key("KEY_A_123456789012345")["last_seen"]


def test_api_full_flow(api):
    call, d, c = api
    cfg = call("get", "/api/v1/config").get_json()
    assert cfg["ok"] and cfg["top_n"] == 5 and cfg["allow_member"] and cfg["points_per_quiz"] == 10
    assert [q["key"] for q in cfg["questions"]] == ["players", "time", "animal", "snack", "phrase"]
    assert set(cfg["questions"][2]["options"][0]) == {"value", "label", "emoji"}

    j = call("post", "/api/v1/member/lookup", json={"member_key": "0912-345-678"}).get_json()
    assert j["ok"] and j["member_no"] == "M1" and "王○○" in j["greeting"] and "小明" not in j["greeting"]
    assert j["points"] == 0
    j = call("post", "/api/v1/member/lookup", json={"member_key": "0999999999"}).get_json()
    assert j["ok"] is False and j["message"]

    # 會員買過殖民火星
    d.add_history("M1", "BG0026", "buy", "2026-01-01")
    r = call("post", "/api/v1/recommend", json={"answers": OWL, "member_no": "M1"})
    j = r.get_json()
    assert r.status_code == 200 and j["ok"] and len(j["results"]) == 5
    names = [x["name"] for x in j["results"]]
    assert "殖民火星" not in names and "農家樂" in names[:2]
    assert j["member"]["excluded_count"] == 1 and j["member"]["personalized"] is True
    first = j["results"][0]
    for k in ("id", "name", "name_en", "players_text", "time_text", "weight_text", "min_age", "shelf", "price",
              "in_stock", "tags", "description", "image_url", "match_percent", "reasons", "played_before", "youtube"):
        assert k in first, k
    assert isinstance(first["in_stock"], bool) and isinstance(first["tags"], list)
    assert first["youtube"]["is_search"] is True and first["youtube"]["video_id"] is None
    assert "search_query" in first["youtube"]["url"]
    log = d.get_quiz_log(j["log_id"])
    assert log["member_no"] == "M1" and log["device_id"] == 1 and not log["claimed"]

    # 不帶會員
    j2 = call("post", "/api/v1/recommend", json={"answers": OWL}).get_json()
    assert j2["member"] is None and "殖民火星" in [x["name"] for x in j2["results"]]

    # 其他平板不能 claim
    r = call("post", f"/api/v1/quiz/{j['log_id']}/claim", key="KEY_B_123456789012345", json={"member_no": "M1"})
    assert r.status_code == 404 and r.get_json()["ok"] is False
    # claim → 加點
    j3 = call("post", f"/api/v1/quiz/{j['log_id']}/claim", json={"member_no": "M1"}).get_json()
    assert j3 == {"ok": True, "message": j3["message"], "points_added": 10, "total_points": 10}
    # 再 claim 同一筆 → 409
    r = call("post", f"/api/v1/quiz/{j['log_id']}/claim", json={"member_no": "M1"})
    assert r.status_code == 409 and r.get_json()["ok"] is False
    # 當日第二次 → ok 但 0 點
    j4 = call("post", f"/api/v1/quiz/{j2['log_id']}/claim", json={"member_no": "M1"}).get_json()
    assert j4["ok"] and j4["points_added"] == 0 and j4["total_points"] == 10 and "每日" in j4["message"]
    # 不存在的會員 / 紀錄
    assert call("post", f"/api/v1/quiz/{j2['log_id']}/claim", json={"member_no": "NOPE"}).status_code == 404
    assert call("post", "/api/v1/quiz/99999/claim", json={"member_no": "M1"}).status_code == 404


def test_api_errors_are_json(api):
    call, d, c = api
    cases = [
        call("post", "/api/v1/recommend", json={"answers": {"players": "99"}}),
        call("post", "/api/v1/recommend", json={"answers": "x"}),
        call("post", "/api/v1/recommend", data="not json", content_type="text/plain"),
        call("post", "/api/v1/recommend", json=[1, 2]),
        call("post", "/api/v1/member/lookup", data="{bad", content_type="application/json"),
    ]
    for r in cases:
        assert r.status_code == 400 and r.is_json and r.get_json()["ok"] is False, r.get_data(as_text=True)
    r = call("get", "/api/v1/nope")
    assert r.status_code == 404 and r.is_json
    r = call("get", "/api/v1/recommend")
    assert r.status_code == 405 and r.is_json
    # API 不受 CSRF 影響（上面的 POST 沒帶 csrf 也沒被 400 HTML 擋）
    assert "<html" not in cases[0].get_data(as_text=True).lower()


def test_api_member_disabled(api):
    call, d, c = api
    d.set_setting("allow_member", False)
    assert call("post", "/api/v1/member/lookup", json={"member_key": "M1"}).status_code == 403
    assert call("get", "/api/v1/config").get_json()["allow_member"] is False
    # 推薦仍可用，但忽略 member_no
    j = call("post", "/api/v1/recommend", json={"answers": OWL, "member_no": "M1"}).get_json()
    assert j["ok"] and j["member"] is None
    assert call("post", f"/api/v1/quiz/{j['log_id']}/claim", json={"member_no": "M1"}).status_code == 403


def test_api_points_disabled_config(api):
    call, d, c = api
    d.set_setting("points_daily_limit", 0)
    assert call("get", "/api/v1/config").get_json()["points_per_quiz"] == 0


def test_api_youtube_video_id(api):
    call, d, c = api
    for x in d.list_games():
        d.update_youtube(x.id, "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "教學", False)
    j = call("post", "/api/v1/recommend", json={"answers": OWL}).get_json()
    yt = j["results"][0]["youtube"]
    assert yt == {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "video_id": "dQw4w9WgXcQ",
                  "is_search": False, "title": "教學"}


def test_api_lookup_rate_limit(api):
    call, d, c = api
    codes = [call("post", "/api/v1/member/lookup", json={"member_key": f"09{i:08d}"}).status_code
             for i in range(25)]
    assert 429 in codes and codes[0] == 200


# ---------------- 網頁前台 + 後台新頁面 ----------------
def csrf_of(c, path):
    html = c.get(path).get_data(as_text=True)
    return re.search(r'name="_csrf" value="([^"]+)"', html).group(1)


def test_web_member_first_flow(tmp_path):
    app = create_app(tmp_path / "w.db")
    d = app.config["DB"]
    GameImporter(d).import_file(SAMPLE.name, SAMPLE.read_bytes())
    d.upsert_member(Member(member_no="M1", name="王小明", phone="0912345678"))
    d.add_history("M1", "BG0026", "buy", "2026-01-01")
    c = app.test_client()
    html = c.get("/").get_data(as_text=True)
    assert "是會員嗎" in html and "你們這群人最像" in html and "🐣" in html
    tok = csrf_of(c, "/")
    j = c.post("/member/lookup", data={"_csrf": tok, "member_key": "0912345678"}).get_json()
    assert j["ok"] and "王○○" in j["greeting"]
    assert c.post("/member/lookup", data={"member_key": "0912345678"}).status_code == 400   # CSRF
    r = c.post("/result", data={"_csrf": tok, "member_key": "0912345678", **OWL})
    html = r.get_data(as_text=True)
    titles = re.findall(r"<h3>([^<]+)", html)
    assert r.status_code == 200 and "王○○" in html and "避開 1 款" in html and "殖民火星" not in titles
    assert "和你常玩的《殖民火星》風格相近" in html
    assert "送你 10 點" in html and d.get_member_by_no("M1").app_points == 10
    assert "/result/" not in html or "member" not in re.findall(r'/result/\d+/(\w+)', html)
    # 略過會員
    r = c.post("/result", data={"_csrf": tok, "member_key": "", **OWL})
    assert "殖民火星" in re.findall(r"<h3>([^<]+)", r.get_data(as_text=True))
    # 查不到會員 → 仍然推薦
    r = c.post("/result", data={"_csrf": tok, "member_key": "000", **OWL}, follow_redirects=True)
    assert r.status_code == 200 and "查不到這個會員" in r.get_data(as_text=True)


def test_admin_new_pages(tmp_path):
    app = create_app(tmp_path / "a.db")
    d = app.config["DB"]
    GameImporter(d).import_file(SAMPLE.name, SAMPLE.read_bytes())
    d.upsert_member(Member(member_no="M1", name="王小明"))
    c = app.test_client()
    tok = csrf_of(c, "/")
    c.post("/admin/login", data={"_csrf": tok, "password": "admin1234"})

    # 平板配對
    r = c.post("/admin/devices", data={"_csrf": tok, "action": "add", "name": "櫃檯平板"}, follow_redirects=True)
    html = r.get_data(as_text=True)
    dev = d.list_devices()[0]
    assert dev["name"] == "櫃檯平板" and len(dev["api_key"]) >= 20 and dev["api_key"] in html and "http://" in html
    assert "1" in c.get("/admin").get_data(as_text=True)
    c.post("/admin/devices", data={"_csrf": tok, "action": "disable", "device_id": dev["id"]})
    assert d.get_device_by_key(dev["api_key"]) is None
    c.post("/admin/devices", data={"_csrf": tok, "action": "enable", "device_id": dev["id"]})
    assert d.get_device_by_key(dev["api_key"]) is not None
    c.post("/admin/devices", data={"_csrf": tok, "action": "delete", "device_id": dev["id"]})
    assert d.list_devices() == []
    assert c.post("/admin/devices", data={"_csrf": tok, "action": "x"}).status_code == 400

    # 題目設定：壞 JSON 不存、好的存、還原
    r = c.post("/admin/quiz", data={"_csrf": tok, "action": "save", "quiz_json": "{oops"})
    assert r.status_code == 200 and "沒有儲存" in r.get_data(as_text=True)
    assert d.get_setting("quiz_config") is None
    data = QuizConfig.default_dict()
    data["questions"][2]["title"] = "你們最像哪種動物？"
    c.post("/admin/quiz", data={"_csrf": tok, "action": "save", "quiz_json": json.dumps(data, ensure_ascii=False)})
    assert "你們最像哪種動物？" in c.get("/").get_data(as_text=True)
    bad = copy.deepcopy(data)
    bad["questions"][2]["options"][0]["tags"] = {"zzz": 1}
    r = c.post("/admin/quiz", data={"_csrf": tok, "action": "save", "quiz_json": json.dumps(bad)})
    assert "zzz" in r.get_data(as_text=True)
    c.post("/admin/quiz", data={"_csrf": tok, "action": "reset"})
    assert "你們這群人最像" in c.get("/").get_data(as_text=True)

    # 設定：點數
    c.post("/admin/settings", data={"_csrf": tok, "store_name": "店", "top_n": "5", "allow_member": "1",
                                    "points_per_quiz": "20", "points_daily_limit": "2"})
    assert d.get_setting("points_per_quiz") == 20 and d.get_setting("points_daily_limit") == 2
    c.post("/admin/settings", data={"_csrf": tok, "store_name": "店", "top_n": "5", "allow_member": "1",
                                    "points_per_quiz": "abc", "points_daily_limit": "-5"})
    assert d.get_setting("points_per_quiz") == 20 and d.get_setting("points_daily_limit") == 0

    # 會員加點 / 扣點
    c.post("/admin/members/M1", data={"_csrf": tok, "action": "add", "amount": "30", "reason": "活動"})
    r = c.post("/admin/members/M1", data={"_csrf": tok, "action": "redeem", "amount": "50", "reason": "飲料"},
               follow_redirects=True)
    assert "點數不足" in r.get_data(as_text=True) and d.get_member_by_no("M1").app_points == 30
    c.post("/admin/members/M1", data={"_csrf": tok, "action": "redeem", "amount": "20", "reason": "飲料"})
    assert d.get_member_by_no("M1").app_points == 10
    r = c.post("/admin/members/M1", data={"_csrf": tok, "action": "add", "amount": "5", "reason": ""},
               follow_redirects=True)
    assert "請填寫原因" in r.get_data(as_text=True)
    html = c.get("/admin/members/M1").get_data(as_text=True)
    assert "兌換：飲料" in html and "-20" in html
    assert ">10<" in c.get("/admin/members").get_data(as_text=True).replace("<b>", "").replace("</b>", "")

    # 匯入銷售紀錄
    data_csv = "會員編號,商品編號,日期\nM1,BG0003,2026-01-01\n".encode()
    r = c.post("/admin/import", data={"_csrf": tok, "kind": "history", "default_kind": "rent",
                                      "file": (io.BytesIO(data_csv), "h.csv")},
               content_type="multipart/form-data", follow_redirects=True)
    assert "銷售／租借紀錄匯入完成" in r.get_data(as_text=True)
    assert d.list_history("M1")[0]["kind"] == "rent"
    assert "卡坦島" in c.get("/admin/members/M1").get_data(as_text=True)

    # POS 頁面儲存銷售紀錄設定
    c.post("/admin/pos", data={"_csrf": tok, "action": "save", "url": "", "history_query": "SELECT * FROM s",
                               "hm_member_no": "card", "hm_pos_sku": "sku", "sync_history": "1",
                               "history_default_kind": "rent"})
    cfg = POSConfig.load(d)
    assert cfg.sync_history and cfg.history_mapping["member_no"] == "card" and cfg.history_default_kind == "rent"
    for path in ["/admin", "/admin/logs", "/admin/pos", "/admin/quiz", "/admin/devices", "/admin/import"]:
        assert c.get(path).status_code == 200, path


def test_admin_pages_require_login(tmp_path):
    c = create_app(tmp_path / "l.db").test_client()
    for path in ["/admin/quiz", "/admin/devices"]:
        assert c.get(path).status_code == 302


# ---------------- DEBUG 第 2 版回歸測試 ----------------
def test_huge_ids_are_404_not_500(api):
    call, d, c = api
    big = "9" * 30
    r = call("post", f"/api/v1/quiz/{big}/claim", json={"member_no": "M1"})
    assert r.status_code == 404 and r.is_json
    assert c.get(f"/game/{big}").status_code == 404
    assert c.get(f"/admin/games/{big}/edit").status_code in (302, 404)


def test_device_key_prefix_or_case_does_not_match(api):
    call, d, c = api
    for k in ("KEY_A_12345678901234", "key_a_123456789012345", "KEY_A_123456789012345x", "%"):
        assert call("get", "/api/v1/ping", key=k).status_code == 401


def test_web_result_member_key_is_rate_limited(tmp_path):
    app = create_app(tmp_path / "rl.db")
    d = app.config["DB"]
    GameImporter(d).import_file(SAMPLE.name, SAMPLE.read_bytes())
    d.upsert_member(Member(member_no="M1", name="王小明", phone="0912345678"))
    c = app.test_client()
    tok = csrf_of(c, "/")
    for i in range(20):
        c.post("/result", data={"_csrf": tok, "member_key": f"09{i:08d}", **OWL})
    # 第 21 次即使猜對也不查會員（不顯示會員問候、不加點）
    html = c.post("/result", data={"_csrf": tok, "member_key": "0912345678", **OWL},
                  follow_redirects=True).get_data(as_text=True)
    assert "太頻繁" in html and "王○○" not in html and d.get_member_by_no("M1").app_points == 0


def test_web_lookup_throttle_not_reset_by_new_sessions(tmp_path):
    app = create_app(tmp_path / "ev.db")
    app.config["LOOKUP_MAX_KEYS"] = 30
    d = app.config["DB"]
    d.upsert_member(Member(member_no="M1", name="王小明", phone="0912345678"))
    codes = []
    for _ in range(120):                      # 每次都是新 session（新的 csrf key）
        c = app.test_client()
        tok = csrf_of(c, "/")
        codes.append(c.post("/member/lookup", data={"_csrf": tok, "member_key": "0900000000"}).status_code)
    assert codes[:20] == [200] * 20 and set(codes[20:]) == {429}


def test_concurrent_claims_no_double_points(tmp_path):
    import threading
    p = tmp_path / "cc.db"
    d = Database(p)
    d.upsert_member(Member(member_no="M1", name="甲"))
    log = d.add_quiz_log({}, [1], device_id=1)
    others = [d.add_quiz_log({}, [1], device_id=1) for _ in range(10)]
    dbs = [Database(p) for _ in range(5)]      # 不同 Database 物件 ≈ 不同行程，只靠 SQLite 鎖
    results = []

    def worker(i, lid):
        results.append(dbs[i % 5].claim_quiz_points(lid, "M1", 10, 2, device_id=1))
    ts = [threading.Thread(target=worker, args=(i, log)) for i in range(10)]
    ts += [threading.Thread(target=worker, args=(i, lid)) for i, lid in enumerate(others)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert sum(1 for r in results if r[0] and r[1]) == 2      # 每日上限 2 次
    assert d.get_member_by_no("M1").app_points == 20
    assert sum(1 for r in results if r[0]) == 11                           # 11 筆紀錄各綁定一次
    assert sum(p["delta"] for p in d.list_points("M1")) == 20


def test_concurrent_redeem_never_negative(tmp_path):
    import threading
    p = tmp_path / "rd.db"
    d = Database(p)
    d.upsert_member(Member(member_no="M1"))
    d.adjust_points("M1", 50, "活動")
    dbs = [Database(p) for _ in range(4)]
    ok = []

    def worker(i):
        try:
            dbs[i % 4].adjust_points("M1", -20, "兌換")
            ok.append(i)
        except ValueError:
            pass
    ts = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(ok) == 2 and d.get_member_by_no("M1").app_points == 10


def test_history_survives_game_delete_and_reimport(db):
    g = db.find_game_by_sku_or_name("BG0003", "")
    db.add_history("X1", "BG0003", "buy", "2026-01-01", game_id=g.id)
    db.delete_game(g.id)
    GameImporter(db).import_file(SAMPLE.name, SAMPLE.read_bytes())
    ng = db.find_game_by_sku_or_name("BG0003", "")
    assert ng.id != g.id
    assert db.history_game_counts("X1") == {ng.id: 1}
    assert db.list_history("X1")[0]["game_name"] == "卡坦島"


def test_history_batch_import_dedupes_within_file(db):
    rows = [{"會員編號": "M1", "商品編號": "BG0003", "遊戲名稱": "", "日期": "2026-01-01"}] * 3 + \
           [{"會員編號": "M1", "商品編號": "", "遊戲名稱": "UNO", "日期": "2026-01-02"},
            {"會員編號": "M1", "商品編號": "", "遊戲名稱": "不存在的遊戲", "日期": "2026-01-03"}]
    r = HistoryImporter(db).import_rows(rows)
    assert r.inserted == 3 and r.skipped == 2
    skus = {h["pos_sku"] for h in db.list_history("M1")}
    assert skus == {"BG0003", "BG0035", "#name:不存在的遊戲"}


def test_epic_time_does_not_reward_short_games(db):
    for a in (dict(players="3-4", time="epic", animal="dog", snack="noodle", phrase="lol"),
              dict(players="2", time="epic", animal="owl", snack="hotpot", phrase="think")):
        for r in Recommender(db.list_games()).recommend(a, top_n=40):
            if r.game.max_time <= 45:
                assert not any("長時間" in x for x in r.reasons), (r.game.name, r.reasons)


def test_quiz_reserved_key_and_reset_clears_custom(tmp_path):
    data = QuizConfig.default_dict()
    data["questions"][2]["key"] = "member_key"
    with pytest.raises(ValueError):
        validate_quiz(data)
    app = create_app(tmp_path / "q.db")
    d = app.config["DB"]
    c = app.test_client()
    tok = csrf_of(c, "/")
    c.post("/admin/login", data={"_csrf": tok, "password": "admin1234"})
    c.post("/admin/quiz", data={"_csrf": tok, "action": "save",
                                "quiz_json": json.dumps(QuizConfig.default_dict())})
    assert "自訂題目" in c.get("/admin/quiz").get_data(as_text=True)
    c.post("/admin/quiz", data={"_csrf": tok, "action": "reset"})
    assert d.get_setting("quiz_config") is None
    assert "預設題目" in c.get("/admin/quiz").get_data(as_text=True)


def test_admin_quiz_bad_inputs_never_500_and_minimal_quiz_works(tmp_path):
    app = create_app(tmp_path / "qb.db")
    d = app.config["DB"]
    GameImporter(d).import_file(SAMPLE.name, SAMPLE.read_bytes())
    d.add_device("A", "KEY_A_123456789012345")
    c = app.test_client()
    tok = csrf_of(c, "/")
    c.post("/admin/login", data={"_csrf": tok, "password": "admin1234"})
    base = QuizConfig.default_dict()
    bads = ["", "null", "[]", "1e999", '{"questions": null}']
    for mut in (lambda x: x["questions"][2].pop("options"),
                lambda x: x["questions"][2]["options"][1].update(value="dog"),
                lambda x: x["questions"][2]["options"][0].update(emoji="🐶" * 30),
                lambda x: x["questions"][1].update(weight="abc"),
                lambda x: x["questions"].pop(0),
                lambda x: x["questions"][0]["options"][0].update(min=None),
                lambda x: x["questions"][3]["options"][0].update(target=float("nan"))):
        b = copy.deepcopy(base)
        mut(b)
        bads.append(json.dumps(b, ensure_ascii=False))
    for text in bads:
        r = c.post("/admin/quiz", data={"_csrf": tok, "action": "save", "quiz_json": text})
        assert r.status_code == 200 and "沒有儲存" in r.get_data(as_text=True), text[:60]
    assert d.get_setting("quiz_config") is None
    # 刪掉 time 題、只剩 players + 一題 tags：前台、API、後台都正常
    mini = copy.deepcopy(base)
    mini["questions"] = [mini["questions"][0], mini["questions"][2]]
    r = c.post("/admin/quiz", data={"_csrf": tok, "action": "save", "quiz_json": json.dumps(mini)})
    assert d.get_setting("quiz_config") is not None
    r = c.post("/result", data={"_csrf": tok, "players": "3-4", "animal": "bee"})
    assert r.status_code == 200 and "契合度" in r.get_data(as_text=True)
    H = {"X-Device-Key": "KEY_A_123456789012345"}
    j = c.get("/api/v1/config", headers=H).get_json()
    assert [q["key"] for q in j["questions"]] == ["players", "animal"]
    r = c.post("/api/v1/recommend", headers=H, json={"answers": {"players": "2", "animal": "fox"}})
    assert r.status_code == 200 and r.get_json()["results"]
    # 平板還用舊題目送答案 → 400 JSON，不是 500
    r = c.post("/api/v1/recommend", headers=H, json={"answers": {"players": "2", "time": "short"}})
    assert r.status_code == 400 and r.is_json
    for path in ("/", "/admin", "/admin/logs", "/admin/quiz"):
        assert c.get(path).status_code == 200, path
    # 資料庫裡的設定被改壞（非 dict）→ 退回預設
    d.set_setting("quiz_config", "garbage")
    assert c.get("/").status_code == 200 and "你們這群人最像" in c.get("/").get_data(as_text=True)


def test_v1_full_database_upgrade(tmp_path):
    """依第 1 版結構建表（無 member_history / points_ledger / devices，quiz_logs 與 members 少欄位）。"""
    p = tmp_path / "v1.db"
    c = sqlite3.connect(p)
    c.executescript("""
      CREATE TABLE games (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, name_en TEXT DEFAULT '',
        min_players INTEGER DEFAULT 2, max_players INTEGER DEFAULT 4, min_time INTEGER DEFAULT 30,
        max_time INTEGER DEFAULT 60, weight REAL DEFAULT 2.0, min_age INTEGER DEFAULT 8, tags TEXT DEFAULT '',
        description TEXT DEFAULT '', pos_sku TEXT DEFAULT '', price REAL DEFAULT 0, stock INTEGER DEFAULT 0,
        rentable INTEGER DEFAULT 1, shelf TEXT DEFAULT '', youtube_url TEXT DEFAULT '', youtube_title TEXT DEFAULT '',
        youtube_is_search INTEGER DEFAULT 0, image_url TEXT DEFAULT '', active INTEGER DEFAULT 1,
        source TEXT DEFAULT 'manual', updated_at TEXT);
      CREATE TABLE members (id INTEGER PRIMARY KEY AUTOINCREMENT, member_no TEXT UNIQUE NOT NULL, name TEXT DEFAULT '',
        phone TEXT DEFAULT '', level TEXT DEFAULT '', points INTEGER DEFAULT 0, source TEXT DEFAULT 'manual', updated_at TEXT);
      CREATE TABLE quiz_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, answers TEXT, result_ids TEXT,
        member_no TEXT DEFAULT '');
      CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
      INSERT INTO games (name, min_players, max_players, tags, pos_sku, weight, min_age)
        VALUES ('舊遊戲', 2, 5, 'party,family', 'OLD01', NULL, NULL);
      INSERT INTO members (member_no, name, phone, points) VALUES ('OLD1', '舊會員', '0911000111', NULL);
      INSERT INTO quiz_logs (created_at, answers, result_ids, member_no) VALUES (NULL, 'not json', '1,x,', 'OLD1');
      INSERT INTO settings VALUES ('store_name', '"舊店名"'), ('top_n', '"abc"'), ('admin_password_hash', '');
    """)
    c.commit()
    c.close()
    app = create_app(p)
    d = app.config["DB"]
    cl = app.test_client()
    html = cl.get("/").get_data(as_text=True)
    assert "舊店名" in html
    tok = re.search(r'name="_csrf" value="([^"]+)"', html).group(1)
    r = cl.post("/result", data={"_csrf": tok, "member_key": "0911000111", "players": "3-4", "time": "short",
                                 "animal": "dog", "snack": "noodle", "phrase": "lol"})
    assert r.status_code == 200 and "舊遊戲" in r.get_data(as_text=True)
    assert d.get_member_by_no("OLD1").app_points == 10
    assert cl.post("/admin/login", data={"_csrf": tok, "password": "admin1234"}).status_code == 302
    for path in ["/admin", "/admin/logs", "/admin/members/OLD1", "/admin/devices", "/admin/quiz", "/admin/games"]:
        assert cl.get(path).status_code == 200, path
