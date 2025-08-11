from flask import Flask, request, jsonify, send_from_directory
import os
import requests
import datetime as dt

app = Flask(__name__, static_url_path="", static_folder="static")

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
YT_BASE = "https://www.googleapis.com/youtube/v3"

# ----------------- 공용 유틸 -----------------
def yt_get(path, params):
    if not YOUTUBE_API_KEY:
        raise RuntimeError("YOUTUBE_API_KEY is not set")
    p = dict(params or {})
    p["key"] = YOUTUBE_API_KEY
    r = requests.get(f"{YT_BASE}/{path}", params=p, timeout=20)
    r.raise_for_status()
    return r.json()

def fetch_view_counts(video_ids):
    """videos.list로 viewCount 가져오기"""
    if not video_ids:
        return {}
    data = yt_get("videos", {"part": "statistics", "id": ",".join(video_ids)})
    out = {}
    for it in data.get("items", []):
        out[it["id"]] = int(it.get("statistics", {}).get("viewCount", 0))
    return out

# ----------------- 헬스체크/정적 -----------------
@app.route("/health")
def health():
    return "ok", 200

@app.route("/")
def home():
    return send_from_directory("static", "index.html")

# ----------------- 검색 (국가/숏폼·롱폼/50개/기간지정) -----------------
# 예) /search?q=정치&region=KR&duration=short&days=3
@app.route("/search")
def search():
    q = (request.args.get("q") or "").strip()
    region = (request.args.get("region") or "").upper().strip()
    duration = (request.args.get("duration") or "any").lower()  # any|short|long
    days = int(request.args.get("days", 5))  # 기본값 5일
    max_results = min(int(request.args.get("max", 50)), 50)

    if not q:
        return jsonify({"items": []})

    published_after = (dt.datetime.utcnow() - dt.timedelta(days=days)).isoformat("T") + "Z"

    params = {
        "part": "snippet",
        "type": "video",
        "q": q,
        "maxResults": max_results,
        "order": "viewCount",        # 조회수 순
        "publishedAfter": published_after,
        "safeSearch": "none",
    }
    if region:
        params["regionCode"] = region
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
            "title": sn["title"],
            "channel": sn["channelTitle"],
            "publishedAt": sn["publishedAt"],
            "thumb": sn["thumbnails"]["medium"]["url"],
            "url": f"https://www.youtube.com/watch?v={vid}",
            "viewCount": vc_map.get(vid, 0)
        })
    items.sort(key=lambda x: x["viewCount"], reverse=True)
    return jsonify({"items": items})

# ----------------- 실시간 랭킹 -----------------
@app.route("/trending")
def trending():
    region = (request.args.get("region") or "KR").upper().strip()
    max_results = min(int(request.args.get("max", 50)), 50)

    data = yt_get("videos", {
        "part": "snippet,statistics",
        "chart": "mostPopular",
        "regionCode": region,
        "maxResults": max_results,
    })

    items = []
    for it in data.get("items", []):
        vid = it["id"]
        sn = it["snippet"]
        st = it.get("statistics", {})
        items.append({
            "title": sn["title"],
            "channel": sn["channelTitle"],
            "publishedAt": sn["publishedAt"],
            "thumb": sn["thumbnails"]["medium"]["url"],
            "url": f"https://www.youtube.com/watch?v={vid}",
            "viewCount": int(st.get("viewCount", 0))
        })
    items.sort(key=lambda x: x["viewCount"], reverse=True)
    return jsonify({"items": items})

# ----------------- 주간 랭킹 (기본 7일) -----------------
@app.route("/weekly")
def weekly():
    region = (request.args.get("region") or "KR").upper().strip()
    q = (request.args.get("q") or "").strip()
    duration = (request.args.get("duration") or "any").lower()
    days = int(request.args.get("days", 7))  # 기본값 7일
    max_results = min(int(request.args.get("max", 50)), 50)

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
            "title": sn["title"],
            "channel": sn["channelTitle"],
            "publishedAt": sn["publishedAt"],
            "thumb": sn["thumbnails"]["medium"]["url"],
            "url": f"https://www.youtube.com/watch?v={vid}",
            "viewCount": vc_map.get(vid, 0)
        })
    items.sort(key=lambda x: x["viewCount"], reverse=True)
    return jsonify({"items": items})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
