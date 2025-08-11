from flask import Flask, request, jsonify, send_from_directory
import os
import requests
import datetime as dt

app = Flask(__name__, static_url_path="", static_folder="static")

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()
YT_BASE = "https://www.googleapis.com/youtube/v3"

# ---------- 공용 유틸 ----------
def safe_json(items=None):
    return jsonify({"items": items or []})

def yt_get(path, params):
    """YouTube Data API 호출 (예외 시 빈 결과 반환)"""
    if not YOUTUBE_API_KEY:
        # 키가 없으면 바로 빈 결과
        return {"items": []}
    try:
        p = dict(params or {})
        p["key"] = YOUTUBE_API_KEY
        r = requests.get(f"{YT_BASE}/{path}", params=p, timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {"items": []}

def fetch_view_counts(video_ids):
    if not video_ids:
        return {}
    data = yt_get("videos", {"part": "statistics", "id": ",".join(video_ids)})
    out = {}
    for it in data.get("items", []):
        try:
            out[it["id"]] = int(it.get("statistics", {}).get("viewCount", 0))
        except Exception:
            pass
    return out

# ---------- 헬스/정적 ----------
@app.route("/health")
def health():
    return "ok", 200

@app.route("/")
def home():
    return send_from_directory("static", "index.html")

# ---------- 검색 ----------
# /search?q=키워드&region=KR&duration=any|short|medium|long&days=5&max=50
@app.route("/search")
def search():
    q = (request.args.get("q") or "").strip()
    region = (request.args.get("region") or "").upper().strip()
    duration = (request.args.get("duration") or "any").lower()
    days = max(1, min(int(request.args.get("days", 5)), 30))
    max_results = max(1, min(int(request.args.get("max", 50)), 50))

    if not q:
        return safe_json()

    published_after = (dt.datetime.utcnow() - dt.timedelta(days=days)).isoformat("T") + "Z"

    params = {
        "part": "snippet",
        "type": "video",
        "q": q,
        "order": "viewCount",
        "publishedAfter": published_after,
        "maxResults": max_results,
        "safeSearch": "none",
    }
    if region:
        params["regionCode"] = region
        if region == "KR":
            params["relevanceLanguage"] = "ko"
    if duration in ("any", "short", "medium", "long"):
        if duration != "any":
            params["videoDuration"] = duration

    data = yt_get("search", params)
    items_raw = data.get("items", [])
    video_ids = [it.get("id", {}).get("videoId") for it in items_raw if it.get("id", {}).get("videoId")]
    vc_map = fetch_view_counts(video_ids)

    items = []
    for it in items_raw:
        vid = it.get("id", {}).get("videoId")
        if not vid:
            continue
        sn = it.get("snippet", {})
        items.append({
            "title": sn.get("title", ""),
            "channel": sn.get("channelTitle", ""),
            "publishedAt": sn.get("publishedAt"),
            "thumb": sn.get("thumbnails", {}).get("medium", {}).get("url"),
            "url": f"https://www.youtube.com/watch?v={vid}",
            "viewCount": vc_map.get(vid, 0)
        })

    items.sort(key=lambda x: x["viewCount"], reverse=True)
    return safe_json(items)

# ---------- 실시간(유튜브) ----------
# /trending?region=KR&max=50
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
        vid = it.get("id")
        sn = it.get("snippet", {})
        st = it.get("statistics", {})
        items.append({
            "title": sn.get("title", ""),
            "channel": sn.get("channelTitle", ""),
            "publishedAt": sn.get("publishedAt"),
            "thumb": sn.get("thumbnails", {}).get("medium", {}).get("url"),
            "url": f"https://www.youtube.com/watch?v={vid}",
            "viewCount": int(st.get("viewCount", 0) or 0)
        })
    items.sort(key=lambda x: x["viewCount"], reverse=True)
    return safe_json(items)

# ---------- 주간 ----------
# /weekly?region=KR&q=키워드&duration=any|short|medium|long&days=7&max=50
@app.route("/weekly")
def weekly():
    region = (request.args.get("region") or "KR").upper().strip()
    q = (request.args.get("q") or "").strip()
    duration = (request.args.get("duration") or "any").lower()
    days = max(1, min(int(request.args.get("days", 7)), 30))
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
    if duration in ("any", "short", "medium", "long"):
        if duration != "any":
            params["videoDuration"] = duration

    data = yt_get("search", params)
    items_raw = data.get("items", [])
    video_ids = [it.get("id", {}).get("videoId") for it in items_raw if it.get("id", {}).get("videoId")]
    vc_map = fetch_view_counts(video_ids)

    items = []
    for it in items_raw:
        vid = it.get("id", {}).get("videoId")
        if not vid:
            continue
        sn = it.get("snippet", {})
        items.append({
            "title": sn.get("title", ""),
            "channel": sn.get("channelTitle", ""),
            "publishedAt": sn.get("publishedAt"),
            "thumb": sn.get("thumbnails", {}).get("medium", {}).get("url"),
            "url": f"https://www.youtube.com/watch?v={vid}",
            "viewCount": vc_map.get(vid, 0)
        })
    items.sort(key=lambda x: x["viewCount"], reverse=True)
    return safe_json(items)

# ---------- 실시간(증가량) - 임시(데이터 없으면 빈 배열) ----------
# /realtime?region=KR&window=60&max=50
@app.route("/realtime")
def realtime():
    # 아직 증분 수집 파이프라인이 없는 경우 빈 결과로 반환
    # 최소한 502가 발생하지 않도록 방어
    return safe_json([])

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
