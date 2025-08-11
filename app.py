# app.py
import os
import datetime as dt
import requests
from flask import Flask, request, jsonify, send_from_directory
import psycopg2
import psycopg2.extras

app = Flask(__name__, static_url_path="", static_folder="static")

# ===== 환경변수 =====
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
YT_BASE = "https://www.googleapis.com/youtube/v3"
DATABASE_URL = os.getenv("DATABASE_URL", "")


# ===== 공용 유틸 =====
def yt_get(path, params):
    """YouTube Data API v3 GET 래퍼."""
    if not YOUTUBE_API_KEY:
        raise RuntimeError("YOUTUBE_API_KEY is not set")
    p = dict(params or {})
    p["key"] = YOUTUBE_API_KEY
    r = requests.get(f"{YT_BASE}/{path}", params=p, timeout=20)
    r.raise_for_status()
    return r.json()


def fetch_view_counts(video_ids):
    """videos.list(statistics)로 viewCount 가져오기."""
    if not video_ids:
        return {}
    data = yt_get("videos", {"part": "statistics", "id": ",".join(video_ids)})
    out = {}
    for it in data.get("items", []):
        out[it["id"]] = int(it.get("statistics", {}).get("viewCount", 0))
    return out


# ===== 헬스/정적 =====
@app.route("/health")
def health():
    return "ok", 200


@app.route("/")
def home():
    return send_from_directory("static", "index.html")


# ===== 검색 (조회수순, 기간=최근 N일 지정 가능, 국가/숏폼/롱폼/최대50) =====
# GET /search?q=키워드&region=KR&duration=any|short|long&days=5&max=50
@app.route("/search")
def search():
    q = (request.args.get("q") or "").strip()
    region = (request.args.get("region") or "").upper().strip()
    duration = (request.args.get("duration") or "any").lower()  # any|short|long
    days = max(0, min(int(request.args.get("days", 0)), 365))   # 0=제한없음
    max_results = max(1, min(int(request.args.get("max", 50)), 50))

    if not q:
        return jsonify({"items": []})

    params = {
        "part": "snippet",
        "type": "video",
        "q": q,
        "maxResults": max_results,
        "order": "viewCount",        # 조회수 순
        "safeSearch": "none",
    }
    if region:
        params["regionCode"] = region
        if region == "KR":
            params["relevanceLanguage"] = "ko"
    if duration in ("short", "long"):
        params["videoDuration"] = duration
    if days > 0:
        published_after = (dt.datetime.utcnow() - dt.timedelta(days=days)).isoformat("T") + "Z"
        params["publishedAfter"] = published_after

    data = yt_get("search", params)
    items_raw = data.get("items", [])
    video_ids = [it["id"]["videoId"] for it in items_raw if it["id"].get("videoId")]
    vc_map = fetch_view_counts(video_ids)

    items = []
    for it in items_raw:
        vid = it["id"]["videoId"]
        sn = it["snippet"]
        items.append({
            "title": sn.get("title"),
            "channel": sn.get("channelTitle"),
            "publishedAt": sn.get("publishedAt"),
            "thumb": sn.get("thumbnails", {}).get("medium", {}).get("url"),
            "url": f"https://www.youtube.com/watch?v={vid}",
            "viewCount": vc_map.get(vid, 0)
        })
    items.sort(key=lambda x: x["viewCount"], reverse=True)
    return jsonify({"items": items})


# ===== 트렌딩(인기 급상승) =====
# GET /trending?region=KR&max=50
@app.route("/trending")
def trending():
    region = (request.args.get("region") or "KR").upper().strip()
    max_results = max(1, min(int(request.args.get("max", 50)), 50))

    data = yt_get("videos", {
        "part": "snippet,statistics",
        "chart": "mostPopular",
        "regionCode": region,
        "maxResults": max_results,
    })

    items = []
    for it in data.get("items", []):
        vid = it["id"]
        sn = it.get("snippet", {})
        st = it.get("statistics", {})
        items.append({
            "title": sn.get("title"),
            "channel": sn.get("channelTitle"),
            "publishedAt": sn.get("publishedAt"),
            "thumb": sn.get("thumbnails", {}).get("medium", {}).get("url"),
            "url": f"https://www.youtube.com/watch?v={vid}",
            "viewCount": int(st.get("viewCount", 0))
        })
    items.sort(key=lambda x: x["viewCount"], reverse=True)
    return jsonify({"items": items})


# ===== 주간 랭킹(최근 N일, 기본 7일) =====
# GET /weekly?region=KR&q=키워드&duration=any|short|long&days=7&max=50
@app.route("/weekly")
def weekly():
    region = (request.args.get("region") or "KR").upper().strip()
    q = (request.args.get("q") or "").strip()
    duration = (request.args.get("duration") or "any").lower()
    days = max(1, min(int(request.args.get("days", 7)), 30))   # 최근 N일 (기본7)
    max_results = max(1, min(int(request.args.get("max", 50)), 50))

    published_after = (dt.datetime.utcnow() - dt.timedelta(days=days)).isoformat("T") + "Z"

    params = {
        "part": "snippet",
        "type": "video",
        "order": "viewCount",
        "maxResults": max_results,
        "regionCode": region,
        "publishedAfter": published_after,
        "safeSearch": "none",
    }
    if q:
        params["q"] = q
        if region == "KR":
            params["relevanceLanguage"] = "ko"
    if duration in ("short", "long"):
        params["videoDuration"] = duration

    data = yt_get("search", params)
    items_raw = data.get("items", [])
    video_ids = [it["id"]["videoId"] for it in items_raw if it["id"].get("videoId")]
    vc_map = fetch_view_counts(video_ids)

    items = []
    for it in items_raw:
        vid = it["id"]["videoId"]
        sn = it["snippet"]
        items.append({
            "title": sn.get("title"),
            "channel": sn.get("channelTitle"),
            "publishedAt": sn.get("publishedAt"),
            "thumb": sn.get("thumbnails", {}).get("medium", {}).get("url"),
            "url": f"https://www.youtube.com/watch?v={vid}",
            "viewCount": vc_map.get(vid, 0)
        })
    items.sort(key=lambda x: x["viewCount"], reverse=True)
    return jsonify({"items": items})


# ===== 실시간 증가량 (DB 스냅샷 기반) =====
def get_realtime_growth(region="KR", window_min=60, limit=50):
    """최근 스냅샷과 window_min 분 전 스냅샷의 조회수 차이를 계산."""
    if not DATABASE_URL:
        return []  # DB 미설정이면 빈 결과

    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("SELECT NOW()")
    now = cur.fetchone()[0]
    since = now - dt.timedelta(minutes=window_min)

    cur.execute("""
      WITH recent AS (
        SELECT DISTINCT ON (video_id)
            video_id, region, ts, view_count, title, channel, thumb
        FROM video_snapshots
        WHERE region = %s
        ORDER BY video_id, ts DESC
      ),
      old AS (
        SELECT DISTINCT ON (video_id)
            video_id, region, ts, view_count
        FROM video_snapshots
        WHERE region = %s AND ts <= %s
        ORDER BY video_id, ts DESC
      )
      SELECT r.video_id, r.title, r.channel, r.thumb,
             r.view_count AS recent_count,
             o.view_count AS old_count,
             (COALESCE(r.view_count,0) - COALESCE(o.view_count,0)) AS delta
      FROM recent r
      LEFT JOIN old o ON r.video_id = o.video_id
      ORDER BY delta DESC
      LIMIT %s
    """, (region, region, since, limit))

    rows = cur.fetchall()
    cur.close()
    conn.close()

    out = []
    for row in rows:
        out.append({
            "videoId": row["video_id"],
            "title": row["title"],
            "channel": row["channel"],
            "thumb": row["thumb"],
            "url": f"https://www.youtube.com/watch?v={row['video_id']}",
            "delta": int(row["delta"] or 0),
            "recentCount": int(row["recent_count"] or 0),
            "oldCount": int(row["old_count"] or 0),
        })
    return out


# GET /realtime?region=KR&window=60&max=50
@app.route("/realtime")
def realtime():
    region = (request.args.get("region") or "KR").upper().strip()
    window = max(5, min(int(request.args.get("window", 60)), 360))
    limit = max(1, min(int(request.args.get("max", 50)), 100))
    try:
        items = get_realtime_growth(region, window, limit)
        return jsonify({"items": items})
    except Exception:
        # 문제 발생 시 502 대신 빈 배열 반환
        return jsonify({"items": []})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
