# -*- coding: utf-8 -*-
# Render + Gunicorn용 (app 객체만 있으면 됨)
import os, sqlite3, requests
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv

# .env 로드(로컬 개발용). Render에서는 대시보드에 환경변수 넣으면 이 단계 없이도 동작.
load_dotenv()

API_KEY = os.getenv("YOUTUBE_API_KEY")
if not API_KEY:
    # Render에 아직 환경변수 안 넣었다면 실패하니, 넣고 다시 배포하세요.
    # (배포 전에 넣어도 되고, 넣고 "Manual Deploy" 해도 됨)
    print("WARNING: YOUTUBE_API_KEY not set. Set it in Render → Environment.")
API_KEY = API_KEY or "DUMMY"

app = Flask(__name__, static_url_path="", static_folder="static")
DB_PATH = "yt_snapshots.db"

GLOBAL_REGIONS = ["IN","US","BR","ID","MX","JP","DE","VN","PH","TR"]
LANG_PREF = {
    "IN": ["en","hi"], "US": ["en"], "BR": ["pt"], "ID": ["id"], "MX": ["es"],
    "JP": ["ja"], "DE": ["de"], "VN": ["vi"], "PH": ["en","tl"], "TR": ["tr"], "KR": ["ko"]
}
POLITICS_KEYWORDS = {"정치","뉴스","정책"}
POLITICS_EXPANSIONS = ["총선","대선","국회","토론","공약","여당","야당","대통령","장관","청문회","뉴스","정책"]

Y_SEARCH = "https://www.googleapis.com/youtube/v3/search"
Y_VIDEOS = "https://www.googleapis.com/youtube/v3/videos"

def ensure_db():
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS snapshots(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      scope TEXT NOT NULL, region TEXT, videoId TEXT NOT NULL,
      title TEXT, channelTitle TEXT, viewCount INTEGER, captured_at TEXT NOT NULL
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_snap_scope_time ON snapshots(scope, captured_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_snap_vid_time ON snapshots(videoId, captured_at)")
    con.commit(); con.close()

def parse_int(x, default=0):
    try: return int(x)
    except: return default

def iso8601_to_seconds(iso_dur: str):
    if not iso_dur or not iso_dur.startswith("PT"): return None
    h=m=s=0; num=""
    for ch in iso_dur[2:]:
        if ch.isdigit(): num += ch
        else:
            if ch=="H": h=int(num or "0")
            if ch=="M": m=int(num or "0")
            if ch=="S": s=int(num or "0")
            num=""
    return h*3600 + m*60 + s

def fetch_videos_detail(video_ids):
    out=[]
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i+50]
        r = requests.get(Y_VIDEOS, params={
            "key": API_KEY, "part":"snippet,statistics,contentDetails", "id":",".join(chunk)
        }, timeout=20)
        r.raise_for_status()
        for it in r.json().get("items", []):
            sec = iso8601_to_seconds(it["contentDetails"]["duration"])
            out.append({
                "videoId": it["id"],
                "title": it["snippet"]["title"],
                "channelTitle": it["snippet"]["channelTitle"],
                "publishedAt": it["snippet"]["publishedAt"],
                "viewCount": parse_int(it["statistics"].get("viewCount")),
                "likeCount": parse_int(it["statistics"].get("likeCount")),
                "url": f"https://www.youtube.com/watch?v={it['id']}",
                "durationSec": sec
            })
    out.sort(key=lambda x: x["viewCount"], reverse=True)
    return out

def search_videos_by_keyword(q, regions, published_after=None, max_per_region=25, shorts=None, is_politics=False):
    collected=[]
    for region in regions:
        langs = LANG_PREF.get(region, ["en"])[:2]
        candidates=[]
        for lang in langs:
            params = {
                "key": API_KEY, "part":"snippet", "type":"video",
                "maxResults": 50 if max_per_region>25 else max_per_region,
                "order":"viewCount", "q": q, "regionCode": region, "relevanceLanguage": lang
            }
            if published_after: params["publishedAfter"] = published_after
            r = requests.get(Y_SEARCH, params=params, timeout=20)
            r.raise_for_status()
            for it in r.json().get("items", []):
                candidates.append(it["id"]["videoId"])
            if len(candidates) >= max_per_region: break

        if not candidates: continue
        unique_ids = list(dict.fromkeys(candidates))[:max_per_region]
        detail = fetch_videos_detail(unique_ids)
        for v in detail:
            sec = v.get("durationSec")
            if shorts is True and sec and sec > 60:  # Shorts 근사: 60초 이하
                continue
            if shorts is False and sec and sec <= 60:
                continue
            v["region"] = region
            if is_politics:
                v["politicsBoost"] = 1 if any(k in v["title"] for k in POLITICS_EXPANSIONS) else 0
            collected.append(v)

    collected.sort(key=lambda x: (x.get("politicsBoost",0), x["viewCount"]), reverse=True)
    return collected

def decide_regions(keyword: str, scope: str):
    key = (keyword or "").strip()
    is_politics = any(k in key for k in POLITICS_KEYWORDS)
    scope = (scope or "AUTO").upper()
    if is_politics: return ["KR"], True
    if scope == "KR": return ["KR"], False
    if scope == "GLOBAL": return GLOBAL_REGIONS, False
    if scope == "MIX": return ["KR"] + GLOBAL_REGIONS, False
    return GLOBAL_REGIONS, False  # AUTO

@app.get("/")
def root():
    return send_from_directory("static", "index.html")

@app.post("/api/search")
def api_search():
    data = request.get_json(force=True)
    keyword = (data.get("keyword") or "").strip()
    scope = (data.get("scope") or "AUTO").upper()
    days = data.get("days")
    shorts = data.get("shorts")  # True/False/None
    if not keyword: return jsonify({"items": [], "routed": []})

    regions, is_politics = decide_regions(keyword, scope)
    published_after = None
    try: d = int(days) if days not in (None,"") else None
    except: d = None
    if d and d>0:
        dt = datetime.utcnow() - timedelta(days=d)
        published_after = dt.replace(tzinfo=timezone.utc).isoformat()

    items = search_videos_by_keyword(keyword, regions, published_after, shorts=shorts, is_politics=is_politics)
    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    for it in items:
        try: pub = datetime.fromisoformat(it["publishedAt"].replace("Z","+00:00"))
        except: pub = now
        days_live = max(1, (now - pub).days)
        it["viewsPerDay"] = round(it["viewCount"] / days_live, 1)
    return jsonify({"items": items, "routed": regions})

@app.get("/api/trending")
def api_trending():
    scope = (request.args.get("scope") or "KR").upper()
    limit = int(request.args.get("limit") or 50)
    shorts = request.args.get("shorts")
    if shorts is not None and shorts!="":
        shorts = shorts.lower()=="true"
    else:
        shorts = None

    regions = ["KR"] if scope=="KR" else GLOBAL_REGIONS
    items=[]
    for region in regions:
        r = requests.get(Y_VIDEOS, params={
            "key": API_KEY, "part":"snippet,statistics,contentDetails",
            "chart":"mostPopular", "maxResults": min(50, limit), "regionCode": region
        }, timeout=20)
        r.raise_for_status()
        for it in r.json().get("items", []):
            sec = iso8601_to_seconds(it["contentDetails"]["duration"])
            vc = parse_int(it["statistics"].get("viewCount"))
            row = {
                "videoId": it["id"], "title": it["snippet"]["title"],
                "channelTitle": it["snippet"]["channelTitle"],
                "publishedAt": it["snippet"]["publishedAt"],
                "viewCount": vc, "url": f"https://www.youtube.com/watch?v={it['id']}",
                "durationSec": sec, "region": region
            }
            if shorts is True and sec and sec>60: continue
            if shorts is False and sec and sec<=60: continue
            items.append(row)
    items.sort(key=lambda x: x["viewCount"], reverse=True)
    return jsonify({"items": items})

@app.post("/api/snapshot")
def api_snapshot():
    ensure_db()
    data = request.get_json(force=True)
    scope = (data.get("scope") or "KR").upper()
    source = (data.get("source") or "trending").lower()
    limit = int(data.get("limit") or 100)
    shorts = data.get("shorts")
    now_iso = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
    to_save=[]

    if source == "trending":
        with app.test_request_context(f"/api/trending?scope={'GLOBAL' if scope=='GLOBAL' else 'KR'}&limit={limit}&shorts={shorts}"):
            resp = api_trending().json
        for it in resp["items"]:
            to_save.append({
                "scope": "GLOBAL_10" if scope=="GLOBAL" else "KR",
                "region": it.get("region"),
                "videoId": it["videoId"],
                "title": it["title"],
                "channelTitle": it["channelTitle"],
                "viewCount": it["viewCount"],
                "captured_at": now_iso
            })
    else:
        kw = (data.get("keyword") or "").strip()
        days = data.get("days") or 7
        if not kw: return jsonify({"ok": False, "error":"keyword required"}), 400
        search_scope = "GLOBAL" if scope=="GLOBAL" else "KR"
        with app.test_request_context("/api/search", json={"keyword":kw,"scope":search_scope,"days":days,"shorts":shorts}):
            resp = api_search().json
        for it in resp["items"][:limit]:
            to_save.append({
                "scope": "GLOBAL_10" if scope=="GLOBAL" else "KR",
                "region": it.get("region"),
                "videoId": it["videoId"],
                "title": it["title"],
                "channelTitle": it["channelTitle"],
                "viewCount": it["viewCount"],
                "captured_at": now_iso
            })

    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.executemany("""
      INSERT INTO snapshots(scope,region,videoId,title,channelTitle,viewCount,captured_at)
      VALUES(:scope,:region,:videoId,:title,:channelTitle,:viewCount,:captured_at)
    """, to_save)
    con.commit(); con.close()
    return jsonify({"ok": True, "saved": len(to_save), "captured_at": now_iso})

@app.get("/api/weekly")
def api_weekly():
    ensure_db()
    scope = (request.args.get("scope") or "KR").upper()
    top = int(request.args.get("top") or 50)
    table_scope = "GLOBAL_10" if scope=="GLOBAL" else "KR"

    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("SELECT MAX(captured_at) FROM snapshots WHERE scope=?", (table_scope,))
    latest = cur.fetchone()[0]
    if not latest:
        con.close()
        return jsonify({"items": [], "note":"스냅샷이 없습니다. 먼저 /api/snapshot 으로 저장하세요."})

    latest_dt = datetime.fromisoformat(latest.replace("Z","+00:00")) if "Z" in latest else datetime.fromisoformat(latest)
    week_ago = (latest_dt - timedelta(days=7)).isoformat()

    cur.execute("SELECT videoId, MAX(viewCount) FROM snapshots WHERE scope=? GROUP BY videoId", (table_scope,))
    latest_map = {vid:vc for vid,vc in cur.fetchall()}

    cur.execute("""
      SELECT s1.videoId, s1.viewCount
      FROM snapshots s1
      JOIN (
        SELECT videoId, MAX(captured_at) AS maxcap
        FROM snapshots
        WHERE scope=? AND captured_at<=?
        GROUP BY videoId
      ) s2 ON s1.videoId=s2.videoId AND s1.captured_at=s2.maxcap
    """, (table_scope, week_ago))
    base_map = {vid:vc for vid,vc in cur.fetchall()}

    cur.execute("SELECT videoId, title, channelTitle, MAX(captured_at) FROM snapshots WHERE scope=? GROUP BY videoId", (table_scope,))
    meta_map = {vid: {"title":t, "channelTitle":c} for vid,t,c,_ in cur.fetchall()}
    con.close()

    out=[]
    for vid, latest_vc in latest_map.items():
        base_vc = base_map.get(vid)
        if base_vc is None: continue
        inc = latest_vc - base_vc
        if inc <= 0: continue
        meta = meta_map.get(vid, {})
        out.append({
            "videoId": vid, "title": meta.get("title",""),
            "channelTitle": meta.get("channelTitle",""),
            "increase7d": inc, "url": f"https://www.youtube.com/watch?v={vid}"
        })
    out.sort(key=lambda x: x["increase7d"], reverse=True)
    return jsonify({"items": out[:top], "latest_capture": latest})
