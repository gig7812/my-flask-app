from flask import Flask, request, jsonify, send_from_directory
import os
import requests
import datetime as dt

app = Flask(__name__, static_url_path="", static_folder="static")

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
YT_BASE = "https://www.googleapis.com/youtube/v3"


# ---------- 공용 유틸 ----------
def yt_get(path, params):
    params = dict(params or {})
    params["key"] = YOUTUBE_API_KEY
    r = requests.get(f"{YT_BASE}/{path}", params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def fetch_view_counts(video_ids):
    """videos.list로 조회수 가져오기"""
    if not video_ids:
        return {}
    data = yt_get("videos", {
        "part": "statistics",
        "id": ",".join(video_ids)
    })
    out = {}
    for it in data.get("items", []):
        st = it.get("statistics", {})
        out[it["id"]] = int(st.get("viewCount", 0))
    return out


# ---------- 헬스체크 ----------
@app.route("/health")
def health():
    return "ok", 200


# ---------- 정적 페이지 ----------
@app.route("/")
def home():
    return send_from_directory("static", "index.html")


# ---------- 검색 (UI 그대로 유지, 결과에 viewCount 추가만) ----------
@app.route("/search")
def search():
    if not YOUTUBE_API_KEY:
        return jsonify({"error": "YOUTUBE_API_KEY is not set"}), 500

    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"items": []})

    # 1) 키워드 검색 (조회수 높은 순)
    data = yt_get("search", {
        "part": "snippet",
        "q": q,
        "type": "video",
        "order": "viewCount",
        "maxResults": 10
    })
    items_raw = data.get("items", [])
    video_ids = [it["id"]["videoId"] for it in items_raw if it["id"].get("videoId")]

    # 2) 각 비디오 조회수
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
            "viewCount": vc_map.get(vid, 0)  # ← 추가 필드 (UI는 그대로)
        })
    return jsonify({"items": items})


# ---------- 실시간(국가별 트렌딩) ----------
# 사용 예: /trending?region=KR
@app.route("/trending")
def trending():
    if not YOUTUBE_API_KEY:
        return jsonify({"error": "YOUTUBE_API_KEY is not set"}), 500

    region = (request.args.get("region") or "KR").upper()

    data = yt_get("videos", {
        "part": "snippet,statistics",
        "chart": "mostPopular",
        "regionCode": region,
        "maxResults": 10
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
    return jsonify({"items": items})


# ---------- 주간 랭킹(최근 7일 업로드 + 조회수순) ----------
# 사용 예: /weekly?region=KR&q=정치   (q는 선택)
@app.route("/weekly")
def weekly():
    if not YOUTUBE_API_KEY:
        return jsonify({"error": "YOUTUBE_API_KEY is not set"}), 500

    region = (request.args.get("region") or "KR").upper()
    q = (request.args.get("q") or "").strip()
    published_after = (dt.datetime.utcnow() - dt.timedelta(days=7)).isoformat("T") + "Z"

    params = {
        "part": "snippet",
        "type": "video",
        "order": "viewCount",
        "maxResults": 10,
        "regionCode": region,
        "publishedAfter": published_after
    }
    if q:
        params["q"] = q

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
    return jsonify({"items": items})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
