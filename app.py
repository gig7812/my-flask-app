from flask import Flask, request, jsonify, send_from_directory
import os, requests, datetime as dt, math
from urllib.parse import urlparse
import psycopg2, psycopg2.extras

app = Flask(__name__, static_url_path="", static_folder="static")

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
YT_BASE = "https://www.googleapis.com/youtube/v3"
DATABASE_URL = os.getenv("DATABASE_URL")  # Render Postgres 접속 문자열

# ---------------- DB 유틸 ----------------
def db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")
    # psycopg2는 연결 풀 없이도 Render 무료 트래픽에서는 충분
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor, sslmode="require")
    return conn

def ensure_schema():
    conn = db(); cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS videos (
        video_id TEXT PRIMARY KEY,
        title TEXT,
        channel TEXT,
        thumb TEXT,
        region TEXT,
        first_seen TIMESTAMPTZ,
        last_seen  TIMESTAMPTZ
    );
    CREATE TABLE IF NOT EXISTS snapshots (
        id BIGSERIAL PRIMARY KEY,
        video_id TEXT REFERENCES videos(video_id) ON DELETE CASCADE,
        captured_at TIMESTAMPTZ,
        view_count BIGINT
    );
    CREATE INDEX IF NOT EXISTS idx_snapshots_vid_time ON snapshots (video_id, captured_at);
    """)
    conn.commit(); cur.close(); conn.close()

ensure_schema()

# ---------------- YouTube 유틸 ----------------
def yt_get(path, params):
    if not YOUTUBE_API_KEY: raise RuntimeError("YOUTUBE_API_KEY is not set")
    p = dict(params or {}); p["key"] = YOUTUBE_API_KEY
    r = requests.get(f"{YT_BASE}/{path}", params=p, timeout=20)
    r.raise_for_status()
    return r.json()

def fetch_view_counts(video_ids):
    if not video_ids: return {}
    data = yt_get("videos", {"part": "statistics,snippet", "id": ",".join(video_ids)})
    out = {}
    for it in data.get("items", []):
        st = it.get("statistics", {}); sn = it.get("snippet", {})
        out[it["id"]] = {
            "viewCount": int(st.get("viewCount", 0)),
            "title": sn.get("title"), "channel": sn.get("channelTitle"),
            "thumb": (sn.get("thumbnails", {}).get("medium", {}) or {}).get("url")
        }
    return out

# ---------------- 기본 페이지/헬스 ----------------
@app.route("/health")
def health(): return "ok", 200

@app.route("/")
def home():  return send_from_directory("static", "index.html")

# ---------------- 기존 검색/트렌딩/주간 ----------------
@app.route("/search")
def search():
    q = (request.args.get("q") or "").strip()
    region = (request.args.get("region") or "").upper().strip()
    duration = (request.args.get("duration") or "any").lower()
    days = max(0, min(int(request.args.get("days", 5)), 30))  # 기본 5일
    max_results = min(max(int(request.args.get("max", 50)),1), 50)
    if not q: return jsonify({"items": []})

    params = {
        "part":"snippet","type":"video","q":q,"maxResults":max_results,
        "order":"viewCount" if days>0 else "relevance","safeSearch":"none"
    }
    if region:
        params["regionCode"]=region
        if region=="KR": params["relevanceLanguage"]="ko"
    if duration in ("short","medium","long"): params["videoDuration"]=duration
    if days>0:
        published_after=(dt.datetime.utcnow()-dt.timedelta(days=days)).isoformat("T")+"Z"
        params["publishedAfter"]=published_after

    data=yt_get("search",params); items_raw=data.get("items",[])
    ids=[it["id"].get("videoId") for it in items_raw if it["id"].get("videoId")]
    vc=fetch_view_counts(ids)
    items=[]
    for it in items_raw:
        vid=it["id"].get("videoId"); sn=it["snippet"]; 
        if not vid: continue
        stat=vc.get(vid,{}); 
        items.append({
            "title": sn.get("title"), "channel": sn.get("channelTitle"),
            "publishedAt": sn.get("publishedAt"),
            "thumb": stat.get("thumb"), "url": f"https://www.youtube.com/watch?v={vid}",
            "viewCount": stat.get("viewCount",0)
        })
    if days>0: items.sort(key=lambda x:x["viewCount"], reverse=True)
    return jsonify({"items":items})

@app.route("/trending")
def trending():
    region=(request.args.get("region") or "KR").upper().strip()
    max_results=min(max(int(request.args.get("max",50)),1),50)
    data=yt_get("videos",{"part":"snippet,statistics","chart":"mostPopular",
                          "regionCode":region,"maxResults":max_results})
    items=[]
    for it in data.get("items",[]):
        st=it.get("statistics",{}); sn=it.get("snippet",{})
        vid=it["id"]
        items.append({
            "title": sn.get("title"), "channel": sn.get("channelTitle"),
            "publishedAt": sn.get("publishedAt"),
            "thumb": (sn.get("thumbnails",{}).get("medium",{}) or {}).get("url"),
            "url": f"https://www.youtube.com/watch?v={vid}",
            "viewCount": int(st.get("viewCount",0))
        })
    items.sort(key=lambda x:x["viewCount"], reverse=True)
    return jsonify({"items":items})

@app.route("/weekly")
def weekly():
    region=(request.args.get("region") or "KR").upper().strip()
    q=(request.args.get("q") or "").strip()
    duration=(request.args.get("duration") or "any").lower()
    days=max(1, min(int(request.args.get("days",7)), 30))  # 기본 7일
    max_results=min(max(int(request.args.get("max",50)),1),50)
    published_after=(dt.datetime.utcnow()-dt.timedelta(days=days)).isoformat("T")+"Z"
    params={"part":"snippet","type":"video","order":"viewCount","maxResults":max_results,
            "regionCode":region,"publishedAfter":published_after,"safeSearch":"none"}
    if q:
        params["q"]=q
        if region=="KR": params["relevanceLanguage"]="ko"
    if duration in ("short","medium","long"): params["videoDuration"]=duration
    data=yt_get("search",params); items_raw=data.get("items",[])
    ids=[it["id"].get("videoId") for it in items_raw if it["id"].get("videoId")]
    vc=fetch_view_counts(ids)
    items=[]
    for it in items_raw:
        vid=it["id"].get("videoId"); sn=it["snippet"]; 
        if not vid: continue
        stat=vc.get(vid,{})
        items.append({
            "title": sn.get("title"), "channel": sn.get("channelTitle"),
            "publishedAt": sn.get("publishedAt"),
            "thumb": stat.get("thumb"), "url": f"https://www.youtube.com/watch?v={vid}",
            "viewCount": stat.get("viewCount",0)
        })
    items.sort(key=lambda x:x["viewCount"], reverse=True)
    return jsonify({"items":items})

# ---------------- “진짜 실시간” 증가량 집계 ----------------
# (A) 스냅샷 수집 잡: /job/ingest?region=KR  (10분마다 실행 권장)
@app.route("/job/ingest")
def job_ingest():
    region=(request.args.get("region") or "KR").upper().strip()
    mode=(request.args.get("mode") or "trending").lower()  # trending|search
    q=(request.args.get("q") or "").strip()
    duration=(request.args.get("duration") or "any").lower()
    max_results=min(max(int(request.args.get("max",50)),1),50)

    # 후보 영상 가져오기
    if mode=="search" and q:
        # 최근 2일 + 조회수순으로 후보 확장
        published_after=(dt.datetime.utcnow()-dt.timedelta(days=2)).isoformat("T")+"Z"
        params={"part":"snippet","type":"video","q":q,"order":"viewCount",
                "maxResults":max_results,"safeSearch":"none","publishedAfter":published_after}
        if region: params["regionCode"]=region
        if duration in ("short","medium","long"): params["videoDuration"]=duration
        data=yt_get("search", params)
        ids=[it["id"].get("videoId") for it in data.get("items",[]) if it["id"].get("videoId")]
    else:
        data=yt_get("videos",{"part":"id","chart":"mostPopular",
                              "regionCode":region,"maxResults":max_results})
        ids=[it["id"] for it in data.get("items",[])]

    # 상세/조회수
    detail=fetch_view_counts(ids)
    now=dt.datetime.utcnow()

    conn=db(); cur=conn.cursor()
    for vid, info in detail.items():
        # upsert videos
        cur.execute("""
            INSERT INTO videos(video_id,title,channel,thumb,region,first_seen,last_seen)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (video_id) DO UPDATE
            SET title=EXCLUDED.title, channel=EXCLUDED.channel, thumb=EXCLUDED.thumb,
                region=EXCLUDED.region, last_seen=EXCLUDED.last_seen
        """, (vid, info.get("title"), info.get("channel"), info.get("thumb"),
              region, now, now))
        # snapshot
        cur.execute("INSERT INTO snapshots(video_id,captured_at,view_count) VALUES (%s,%s,%s)",
                    (vid, now, info.get("viewCount",0)))
    conn.commit(); cur.close(); conn.close()
    return jsonify({"ok": True, "count": len(detail)})

# (B) 증가량 랭킹 조회: /realtime?region=KR&window=60&max=50
@app.route("/realtime")
def realtime():
    region=(request.args.get("region") or "KR").upper().strip()
    window=min(max(int(request.args.get("window",60)), 5), 1440)  # 분단위, 5~1440
    max_results=min(max(int(request.args.get("max",50)),1),50)

    since=dt.datetime.utcnow() - dt.timedelta(minutes=window)

    conn=db(); cur=conn.cursor()
    # 최근 window 내 스냅샷 불러오기
    cur.execute("""
      SELECT s.video_id, s.captured_at, s.view_count, v.title, v.channel, v.thumb
      FROM snapshots s
      JOIN videos v ON v.video_id=s.video_id
      WHERE v.region=%s AND s.captured_at >= %s
      ORDER BY s.video_id, s.captured_at
    """, (region, since))
    rows=cur.fetchall()
    cur.close(); conn.close()

    # 비디오별 증가량 계산 (첫 스냅샷 대비 마지막 스냅샷)
    by_vid={}
    for r in rows:
        vid=r["video_id"]
        arr=by_vid.setdefault(vid, [])
        arr.append(r)
    items=[]
    for vid, arr in by_vid.items():
        first=arr[0]; last=arr[-1]
        delta=max(0, int(last["view_count"]) - int(first["view_count"]))
        items.append({
            "title": last["title"], "channel": last["channel"],
            "publishedAt": None,  # 스냅샷 기준이라 생략
            "thumb": last["thumb"],
            "url": f"https://www.youtube.com/watch?v={vid}",
            "viewCount": int(last["view_count"]),
            "delta": delta
        })
    items.sort(key=lambda x: x["delta"], reverse=True)
    return jsonify({"windowMinutes": window, "items": items[:max_results]})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
