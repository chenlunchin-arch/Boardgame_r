"""自動測試：python -m pytest tests -q"""
import io
import re
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from core.database import Database  # noqa: E402
from core.importer import GameImporter, MemberImporter, TableReader  # noqa: E402
from core.models import BoardGame, normalize_tags  # noqa: E402
from core.pos_connector import POSConfig, POSConnector  # noqa: E402
from core.recommender import Recommender  # noqa: E402
from core.youtube_finder import YouTubeFinder, extract_video_id, embed_url  # noqa: E402

SAMPLE = ROOT / "sample_data" / "games_sample.csv"


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "t.db")
    GameImporter(d).import_file(SAMPLE.name, SAMPLE.read_bytes())
    return d


# ---------------- 模型 / 匯入 ----------------
def test_normalize_tags():
    assert normalize_tags("派對、合作,strategy") == ["party", "coop", "strategy"]
    assert normalize_tags("不存在,推理") == ["deduction"]


def test_sample_import(db):
    games = db.list_games()
    assert len(games) == 40
    g = db.find_game_by_sku_or_name("BG0003", "")
    assert g.name == "卡坦島" and g.min_players == 3 and g.max_players == 4
    assert g.min_time == 60 and g.max_time == 120 and "strategy" in g.tags


def test_reimport_updates_not_duplicates(db):
    r = GameImporter(db).import_file(SAMPLE.name, SAMPLE.read_bytes())
    assert r.inserted == 0 and r.updated == 40
    assert len(db.list_games()) == 40


def test_reimport_keeps_youtube(db):
    g = db.find_game_by_sku_or_name("BG0001", "")
    db.update_youtube(g.id, "https://www.youtube.com/watch?v=abcdefghijk", "教學", False)
    GameImporter(db).import_file(SAMPLE.name, SAMPLE.read_bytes())
    assert db.get_game(g.id).youtube_url.endswith("abcdefghijk")


def test_big5_csv_and_alias_headers(tmp_path):
    d = Database(tmp_path / "b.db")
    text = "品名,人數,時間,分類,貨號\n測試遊戲,2~6人,20分鐘,派對;反應,X1\n"
    r = GameImporter(d).import_file("a.csv", text.encode("cp950"))
    assert r.inserted == 1
    g = d.list_games()[0]
    assert (g.min_players, g.max_players, g.min_time, g.max_time) == (2, 6, 20, 20)
    assert g.tags == ["party", "dexterity"] and g.pos_sku == "X1"


def test_xlsx_import(tmp_path):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["會員編號", "姓名", "手機", "點數"])
    ws.append(["M1", "王小明", "0912-345-678", 50])
    buf = io.BytesIO()
    wb.save(buf)
    d = Database(tmp_path / "x.db")
    r = MemberImporter(d).import_file("m.xlsx", buf.getvalue())
    assert r.inserted == 1
    m = d.find_member("0912345678")
    assert m.member_no == "M1" and m.points == 50 and m.masked_phone == "0912***678"


def test_export_roundtrip(db, tmp_path):
    data = GameImporter(db).export_csv()
    rows = TableReader.read("e.csv", data)
    assert len(rows) == 40
    d2 = Database(tmp_path / "r.db")
    assert GameImporter(d2).import_rows(rows).inserted == 40
    assert d2.find_game_by_sku_or_name("BG0012", "").tags == db.find_game_by_sku_or_name("BG0012", "").tags


# ---------------- 推薦 ----------------
def rec_names(db, **a):
    return [r.game.name for r in Recommender(db.list_games()).recommend(a)]


def test_couple_gets_two_player_games(db):
    a = dict(players="2", time="short", animal="owl", snack="chicken", phrase="think")
    names = rec_names(db, **a)
    assert names[0] in {"拼布對決", "七大奇蹟對決", "失落的城市"}
    assert len({"拼布對決", "七大奇蹟對決", "失落的城市"} & set(names[:3])) >= 2
    for r in Recommender(db.list_games()).recommend(a):
        assert r.game.min_players <= 2 <= r.game.max_players


def test_big_party_deduction(db):
    names = rec_names(db, players="7+", time="medium", animal="fox", snack="noodle", phrase="culprit")
    assert names[0] in {"阿瓦隆", "狼人殺", "矮人礦坑", "犯人在跳舞", "截碼戰"}


def test_newbie_family_avoids_heavy(db):
    # 🐣 雞媽媽 + 🍜 泡麵：不推 14+、不推 12+（kid_age）、不推中重度
    for t in ("short", "medium", "long", "epic"):
        recs = Recommender(db.list_games()).recommend(
            dict(players="3-4", time=t, animal="hen", snack="noodle", phrase="lol"))
        assert all(r.game.weight < 2.6 for r in recs), t
        assert all(r.game.min_age < 12 for r in recs), t
        assert not any("bluff" in r.game.tags for r in recs[:3]), t


def test_gamer_long_strategy(db):
    for t in ("long", "epic"):
        names = rec_names(db, players="3-4", time=t, animal="owl", snack="hotpot", phrase="think")
        assert {"農家樂", "殖民火星"} <= set(names[:3]), (t, names)


def test_coop(db):
    names = rec_names(db, players="3-4", time="medium", animal="bee", snack="chicken", phrase="thanks")
    assert all("coop" in n.tags for n in [r.game for r in Recommender(db.list_games()).recommend(
        dict(players="3-4", time="medium", animal="bee", snack="chicken", phrase="thanks"))])
    assert names[0] in {"瘟疫危機", "禁制之島", "花火", "Mysterium", "火線救援", "心靈同步", "Just One"}


def test_invalid_answer(db):
    with pytest.raises(ValueError):
        Recommender(db.list_games()).recommend({"players": "99"})


def test_relaxed_when_no_player_fit(tmp_path):
    d = Database(tmp_path / "s.db")
    d.save_game(BoardGame(name="四人遊戲", min_players=4, max_players=4, tags=["party"]))
    recs = Recommender(d.list_games()).recommend(
        dict(players="7+", time="short", animal="dog", snack="noodle", phrase="lol"))
    assert recs and "最接近" in recs[0].reasons[0]


def test_inactive_excluded(db):
    for g in db.list_games():
        if g.name != "UNO":
            g.active = False
            db.save_game(g)
    names = rec_names(db, players="3-4", time="short", animal="hen", snack="noodle", phrase="lol")
    assert names == ["UNO"]


# ---------------- YouTube ----------------
def test_youtube_without_key(db):
    g = db.find_game_by_sku_or_name("BG0002", "")
    v = YouTubeFinder().find(g)
    assert v.is_search and "search_query" in v.url


def test_youtube_with_key_picks_tutorial(db):
    g = db.find_game_by_sku_or_name("BG0002", "")
    fake = {"items": [
        {"id": {"videoId": "AAAAAAAAAAA"}, "snippet": {"title": "卡卡頌 開箱", "channelTitle": "x"}},
        {"id": {"videoId": "BBBBBBBBBBB"}, "snippet": {"title": "卡卡頌 桌遊教學 規則說明", "channelTitle": "y"}},
    ]}
    calls = []

    def http_get(url):
        calls.append(url)
        assert "key=TESTKEY" in url
        return fake
    v = YouTubeFinder(api_key="TESTKEY", http_get=http_get).find(g)
    assert not v.is_search and v.url.endswith("BBBBBBBBBBB")
    assert len(calls) == 1      # 中文結果夠好就不再查英文


def test_video_id_parsing():
    assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10") == "dQw4w9WgXcQ"
    assert extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert embed_url("https://www.youtube.com/results?search_query=x") is None


# ---------------- POS ----------------
@pytest.fixture
def pos_db(tmp_path):
    p = tmp_path / "pos.db"
    c = sqlite3.connect(p)
    c.executescript("""
      CREATE TABLE products (item_no TEXT, item_name TEXT, sale_price REAL, qty INT, cat TEXT, players TEXT);
      INSERT INTO products VALUES ('BG0001','璀璨寶石',1290,7,'桌遊','2-4');
      INSERT INTO products VALUES ('NEW01','新進桌遊',800,2,'桌遊','3-5');
      INSERT INTO products VALUES ('DRK01','可樂',35,99,'飲料','');
      CREATE TABLE vip (card_no TEXT, cname TEXT, mobile TEXT, pts INT);
      INSERT INTO vip VALUES ('V001','林小華','0922000111',300);
      INSERT INTO vip VALUES ('V002','陳大同','0933000222',0);
    """)
    c.commit()
    c.close()
    return p


def test_pos_query_guard():
    for bad in ["DELETE FROM x", "SELECT 1; DROP TABLE x", "update a set b=1", ""]:
        with pytest.raises(ValueError):
            POSConnector.check_query(bad)
    assert POSConnector.check_query("SELECT * FROM a;") == "SELECT * FROM a"


def test_pos_sync(db, pos_db):
    cfg = POSConfig(
        url=f"sqlite:///{pos_db}",
        game_query="SELECT * FROM products WHERE cat='桌遊'",
        game_mapping={"name": "item_name", "pos_sku": "item_no", "price": "sale_price", "stock": "qty"},
        member_query="SELECT * FROM vip",
        member_mapping={"member_no": "card_no", "name": "cname", "phone": "mobile", "points": "pts"},
    )
    conn = POSConnector(cfg)
    assert conn.test_connection() == "連線成功"
    res = conn.sync(db)
    assert res["games"].inserted == 1 and res["games"].updated == 1
    assert res["members"].inserted == 2
    g = db.find_game_by_sku_or_name("BG0001", "")
    assert g.price == 1290 and g.stock == 7 and "strategy" in g.tags   # 標籤保留
    new = db.find_game_by_sku_or_name("NEW01", "")
    assert (new.min_players, new.max_players) == (3, 5) and new.source == "pos"
    assert db.find_member("0922000111").name == "林小華"
    assert POSConfig(url="mysql+pymysql://u:secret@h/db").masked_url == "mysql+pymysql://u:****@h/db"


# ---------------- Web ----------------
@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "web.db")
    GameImporter(app.config["DB"]).import_file(SAMPLE.name, SAMPLE.read_bytes())
    app.config["TESTING"] = True
    return app.test_client(), app


def csrf_of(c, path):
    html = c.get(path).get_data(as_text=True)
    return re.search(r'name="_csrf" value="([^"]+)"', html).group(1)


def test_web_flow(client, pos_db):
    c, app = client
    db = app.config["DB"]
    assert c.get("/").status_code == 200
    token = csrf_of(c, "/")
    r = c.post("/result", data={"_csrf": token, "players": "5-6", "time": "short",
                                "animal": "dog", "snack": "noodle", "phrase": "lol"})
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "契合度" in html and "搜尋教學影片" in html
    log_id = int(re.search(r"/result/(\d+)/member", html).group(1))

    # 沒 csrf 會被擋
    assert c.post("/result", data={"players": "2"}).status_code == 400

    # 後台需要登入
    assert c.get("/admin").status_code == 302
    r = c.post("/admin/login", data={"_csrf": token, "password": "admin1234"})
    assert r.status_code == 302
    for path in ["/admin", "/admin/games", "/admin/games?missing=1", "/admin/youtube", "/admin/import",
                 "/admin/pos", "/admin/members", "/admin/logs", "/admin/settings", "/admin/games/new",
                 "/admin/quiz", "/admin/devices", "/admin/template/history.csv",
                 "/admin/games/1/edit", "/browse", "/browse?tag=coop&q=卡", "/game/1",
                 "/admin/export/games.csv", "/admin/template/games.csv"]:
        assert c.get(path).status_code == 200, path

    # 會員匯入 + 前台綁定
    data = "會員編號,姓名,手機\nM9,張三,0911222333\n".encode("utf-8")
    r = c.post("/admin/import", data={"_csrf": token, "kind": "members",
                                      "file": (io.BytesIO(data), "m.csv")},
               content_type="multipart/form-data", follow_redirects=True)
    assert "新增 1 筆" in r.get_data(as_text=True)
    j = c.post(f"/result/{log_id}/member", data={"_csrf": token, "member_key": "0911-222-333"}).get_json()
    assert j["ok"] and "張" in j["message"] and "三" not in j["message"]
    assert db.get_member_by_no("M9").app_points == 10
    # 同一筆不能再領第二次
    j = c.post(f"/result/{log_id}/member", data={"_csrf": token, "member_key": "M9"}).get_json()
    assert not j["ok"]
    assert c.get("/admin/members/M9").status_code == 200
    assert db.list_quiz_logs(member_no="M9")

    # 編輯桌遊 + 手動貼影片
    r = c.post("/admin/games/1/edit", data={"_csrf": token, "name": "改名測試", "min_players": "2",
                                            "max_players": "4", "tags": ["party", "coop"],
                                            "youtube_url": "https://youtu.be/dQw4w9WgXcQ", "active": "1"})
    assert r.status_code == 302
    g = db.get_game(1)
    assert g.name == "改名測試" and g.tags == ["party", "coop"] and not g.youtube_is_search
    assert "youtube-nocookie.com/embed/dQw4w9WgXcQ" in c.get("/game/1").get_data(as_text=True)

    # YouTube 批次（無金鑰 → 搜尋頁）
    c.post("/admin/youtube", data={"_csrf": token, "action": "batch", "limit": "5"})
    assert sum(1 for x in db.list_games() if x.youtube_is_search) == 5

    # POS 設定 + 預覽 + 同步
    r = c.post("/admin/pos", data={"_csrf": token, "action": "preview_games", "url": f"sqlite:///{pos_db}",
                                   "game_query": "SELECT * FROM products", "member_query": "SELECT * FROM vip",
                                   "gm_name": "item_name", "gm_pos_sku": "item_no", "mm_member_no": "card_no",
                                   "mm_name": "cname", "mm_phone": "mobile", "sync_games": "1", "sync_members": "1"})
    assert "item_name" in r.get_data(as_text=True)
    r = c.post("/admin/pos", data={"_csrf": token, "action": "sync", "url": f"sqlite:///{pos_db}",
                                   "game_query": "SELECT * FROM products WHERE cat='桌遊'",
                                   "member_query": "SELECT * FROM vip", "gm_name": "item_name",
                                   "gm_pos_sku": "item_no", "mm_member_no": "card_no", "mm_name": "cname",
                                   "mm_phone": "mobile", "sync_games": "1", "sync_members": "1"},
               follow_redirects=True)
    assert "桌遊同步" in r.get_data(as_text=True)
    assert db.find_member("V001") is not None

    # 改密碼
    c.post("/admin/settings", data={"_csrf": token, "action": "password", "current": "admin1234",
                                    "new": "newpass99", "new2": "newpass99"})
    c.get("/admin/logout")
    assert c.post("/admin/login", data={"_csrf": token, "password": "admin1234"}).status_code == 200
    assert c.post("/admin/login", data={"_csrf": token, "password": "newpass99"}).status_code == 302

    # 刪除
    c.post("/admin/games/2/delete", data={"_csrf": token})
    assert db.get_game(2) is None


# ---------------- DEBUG 回歸測試 ----------------
def test_pos_query_guard_bypasses():
    for bad in ["SELECT * INTO t2 FROM a", "select * from a into outfile '/tmp/x'",
                "WITH x AS (DELETE FROM a RETURNING *) SELECT * FROM x",
                "SELECT 1 /*!50000 , sleep(1) */", "SELECT 1 -- \n; DROP TABLE x",
                "sElEcT 1 UNION SELECT * FROM a; UpDaTe a SET b=1"]:
        with pytest.raises(ValueError):
            POSConnector.check_query(bad)
    # REPLACE() 字串函式、updated_at 這種欄名不可誤擋
    assert POSConnector.check_query("SELECT REPLACE(name,' ','') AS n, updated_at FROM a")


def test_pos_query_with_colon_literal(tmp_path):
    p = tmp_path / "c.db"
    c = sqlite3.connect(p)
    c.executescript("CREATE TABLE t(a TEXT); INSERT INTO t VALUES ('12:30');")
    c.commit()
    c.close()
    rows = POSConnector(POSConfig(url=f"sqlite:///{p}")).fetch("SELECT * FROM t WHERE a='12:30'")
    assert rows == [{"a": "12:30"}]


def test_masked_url_password_with_at_and_restore():
    cfg = POSConfig(url="mysql+pymysql://u:p@ss@h:3306/db")
    assert cfg.masked_url == "mysql+pymysql://u:****@h:3306/db"
    assert cfg.password == "p@ss"


def test_pos_sync_does_not_wipe_players_time(db, pos_db):
    before = db.find_game_by_sku_or_name("BG0003", "")
    GameImporter(db).import_rows([{"商品編號": "BG0003", "遊戲名稱": "卡坦島", "售價": "1700"}], source="pos")
    after = db.find_game_by_sku_or_name("BG0003", "")
    assert (after.min_players, after.max_players, after.min_time, after.max_time, after.weight, after.min_age) == \
           (before.min_players, before.max_players, before.min_time, before.max_time, before.weight, before.min_age)
    assert after.price == 1700


def test_same_name_different_sku_kept_separate(db):
    r = GameImporter(db).import_rows([{"商品編號": "BG9999", "遊戲名稱": "卡坦島", "售價": "500"}])
    assert r.inserted == 1
    skus = sorted(x.pos_sku for x in db.list_games(keyword="卡坦島"))
    assert skus == ["BG0003", "BG9999"]


def test_bad_numbers_and_urls_sanitized(tmp_path):
    d = Database(tmp_path / "n.db")
    rows = [{"遊戲名稱": "怪資料", "售價": "nan", "庫存": "inf", "難度": "abc", "人數": "5+",
             "教學影片": "javascript:alert(1)", "圖片": "data:text/html,x"},
            {"遊戲名稱": "", "售價": "1"},
            {"遊戲名稱": "千分位", "售價": "1,350", "時間": "45"}]
    r = GameImporter(d).import_rows(rows)
    assert r.inserted == 2 and r.skipped == 1
    g = d.find_game_by_sku_or_name("", "怪資料")
    assert g.price == 0 and g.stock == 0 and g.weight == 2.0 and g.min_players == 5
    assert g.youtube_url == "" and g.image_url == ""
    assert d.find_game_by_sku_or_name("", "千分位").price == 1350


def test_empty_and_broken_files(tmp_path):
    d = Database(tmp_path / "e.db")
    assert GameImporter(d).import_file("e.csv", b"").errors
    assert GameImporter(d).import_file("e.csv", "遊戲名稱\n".encode()).errors
    assert GameImporter(d).import_file("e.csv", "foo,bar\n1,2\n".encode()).errors
    with pytest.raises(ValueError):
        GameImporter(d).import_file("e.xlsx", b"not a zip")
    with pytest.raises(ValueError):
        GameImporter(d).import_file("e.xls", b"x")


def test_member_import_excel_numbers_and_keep_phone(tmp_path):
    d = Database(tmp_path / "m.db")
    MemberImporter(d).import_rows([{"會員編號": 1001.0, "姓名": "甲", "手機": 912345678.0}])
    m = d.find_member("1001")
    assert m is not None and m.phone == "0912345678"
    MemberImporter(d).import_rows([{"會員編號": "1001", "點數": "50"}])   # 沒有手機欄 → 保留
    m = d.find_member("1001")
    assert m.phone == "0912345678" and m.name == "甲" and m.points == 50


def test_recommender_score_nonnegative_and_stable(db):
    a = dict(players="3-4", time="epic", animal="hen", snack="noodle", phrase="comeback")
    r1 = Recommender(db.list_games()).recommend(a, top_n=40)
    r2 = Recommender(list(reversed(db.list_games()))).recommend(a, top_n=40)
    assert all(r.score >= 0 for r in r1)
    assert [r.game.id for r in r1] == [r.game.id for r in r2]


def test_empty_db_result(tmp_path):
    app = create_app(tmp_path / "empty.db")
    c = app.test_client()
    token = csrf_of(c, "/")
    r = c.post("/result", data={"_csrf": token, "players": "2", "time": "short", "animal": "dog",
                                "snack": "noodle", "phrase": "lol"})
    assert r.status_code == 200 and "沒有符合" in r.get_data(as_text=True)


def test_web_edge_cases(client):
    c, app = client
    db = app.config["DB"]
    token = csrf_of(c, "/")
    # 缺欄位 / 亂填答案 → 回首頁，不是 500
    assert c.post("/result", data={"_csrf": token}).status_code == 302
    assert c.post("/result", data={"_csrf": token, "players": "x"}).status_code == 302
    # open redirect
    for evil in ["//evil.com", "/\\evil.com", "https://evil.com", "javascript:alert(1)"]:
        r = c.post(f"/admin/login?next={evil}", data={"_csrf": token, "password": "admin1234"})
        assert r.status_code == 302 and "evil" not in r.headers["Location"] and "javascript" not in r.headers["Location"]
        c.get("/admin/logout")
    c.post("/admin/login?next=/admin/games", data={"_csrf": token, "password": "admin1234"})
    r = c.post("/admin/games/1/youtube", data={"_csrf": token, "back": "//evil.com"})
    assert "evil" not in r.headers["Location"]
    # 非數字輸入
    assert c.post("/admin/youtube", data={"_csrf": token, "action": "batch", "limit": "abc"}).status_code == 302
    assert c.post("/admin/settings", data={"_csrf": token, "top_n": "x", "allow_member": "1"}).status_code == 302
    assert db.get_setting("top_n") == 5
    r = c.post("/admin/games/new", data={"_csrf": token, "name": "空值", "price": "", "weight": "nan",
                                         "min_players": "-3", "youtube_url": "javascript:alert(1)"})
    assert r.status_code == 302
    g = db.find_game_by_sku_or_name("", "空值")
    assert g.youtube_url == "" and g.min_players >= 1 and g.weight == 2.0
    assert c.get(f"/admin/games/{g.id}/edit").status_code == 200
    # 404 / 未知 kind
    assert c.get("/admin/games/99999/edit").status_code == 404
    assert c.get("/admin/members/NOPE").status_code == 404
    assert c.get("/no-such-page").status_code == 404
    assert c.post("/admin/import", data={"_csrf": token, "kind": "x"}).status_code == 400
    # 會員綁定只能綁自己裝置產生的紀錄
    j = c.post("/result/99999/member", data={"_csrf": token, "member_key": "x"}).get_json()
    assert not j["ok"]
    # 會員編號含斜線
    db.upsert_member(__import__("core.models", fromlist=["Member"]).Member(member_no="A/1", name="斜線"))
    assert c.get("/admin/members/A/1").status_code == 200
