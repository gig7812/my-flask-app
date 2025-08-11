from flask import Flask, request, jsonify, send_from_directory
import os
import requests
import datetime as dt

app = Flask(__name__, static_url_path="", static_folder="static")

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
YT_BASE = "https://www.googleapis.com/youtube/v3"


# ---------- 공용 유틸 ----------
def yt_get(path, params):
    """실패 시 raise_for_status()로 예외 발생(원본)"""
    if not YOUTUBE_API_KEY:
        raise RuntimeError("YOUTUBE_API_KEY is not set")
    p = dict(params or {})
    p["key"] = YOUTUBE_API_KEY
    r = requests.get(f"{YT_BASE}/{path}", params=p, timeout=20)
    r.raise_for_status()
    return r.json()


def yt_get_safe(path, params):
    """API 에러가 나도 서버가 502/500로 죽지 않도록 안전 래퍼"""
    try:
        return yt_get(path, params), None
    except requests.exceptions.HTTPError as e:
        try:
            return e.response.json(), str(e)
        except Exception:
            return {"error": "http_error", "detail": str(e)}, str(e)
    except Exception as e:
        return {"error": "unknown_error", "detail": str(e)}, str(e)


def fetch_view_counts(video_ids):
    """videos.list로 viewCount 가져오기(안전 호출)"""
    if not video_ids:
        return {}
    data, err = yt_get_safe("videos", {"part": "statistics", "id": ",".join(video_ids)})
    out = {}
    for it in data.get("items", []) if isinstance(data, dict) else []:
        out[it.get("id", "")] = int(it.get("statistics", {}).get("viewCount", 0))
    return out


# ---------- 헬스/정적 ----------
@app.route("/health")
def health():
    return "ok", 200


@app.route("/")
def home():
    return send_from_directory("static", "index.html")


# ---------- 검색 ----------
# 예) /search?q=정치&region=KR&duration=any|short|long&days=5&max=50
@app.route("/search")
def search():
    q = (request.args.get("q") or "").strip()
    region = (request.args.get("region") or "").upper().strip()
    duration = (request.args.get("duration") or "any").lower()  # any|short|long
    max_results = max(1, min(int(request.args.get("max", 50)), 50))
    days = int(request.args.get("days", 0))  # 0이면 기간 제한 없음

    if not q:
        return jsonify({"items": [], "note": "검색어가 비어있습니다."}), 200

    params = {
        "part": "snippet",
        "type": "video",
        "q": q,
        "maxResults": max_results,
        "order": "viewCount",  # 조회수 순
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

    data, err = yt_get_safe("search", params)
    if err:
        return jsonify({"items": [], "error": data}), 200

    items_raw = data.get("items", [])
    video_ids = [it.get("id", {}).get("videoId") for it in items_raw if it.get("id", {}).get("videoId")]
    vc_map = fetch_view_counts(video_ids)

    items = []
    for it in items_raw:
        vid = it.get("id", {}).get("videoId")
        sn = it.get("snippet", {})
        if not vid:
            continue
        items.append({
            "title": sn.get("title"),
            "channel": sn.get("channelTitle"),
            "publishedAt": sn.get("publishedAt"),
            "thumb": sn.get("thumbnails", {}).get("medium", {}).get("url"),
            "url": f"https://www.youtube.com/watch?v={vid}",
            "viewCount": vc_map.get(vid, 0)
        })
    items.sort(key=lambda x: x["viewCount"], reverse=True)
    return jsonify({"items": items}), 200


# ---------- 실시간 인기(YouTube Most Popular) ----------
# 예) /trending?region=KR&max=50
@app.route("/trending")
def trending():
    region = (request.args.get("region") or "KR").upper().strip()
    max_results = max(1, min(int(request.args.get("max", 50)), 50))

    data, err = yt_get_safe("videos", {
        "part": "snippet,statistics",
        "chart": "mostPopular",
        "regionCode": region,
        "maxResults": max_results,
    })
    if err:
        return jsonify({"items": [], "error": data}), 200

    items = []
    for it in data.get("items", []):
        vid = it.get("id")
        sn = it.get("snippet", {})
        st = it.get("statistics", {})
        if not vid:
            continue
        items.append({
            "title": sn.get("title"),
            "channel": sn.get("channelTitle"),
            "publishedAt": sn.get("publishedAt"),
            "thumb": sn.get("thumbnails", {}).get("medium", {}).get("url"),
            "url": f"https://www.youtube.com/watch?v={vid}",
            "viewCount": int(st.get("viewCount", 0))
        })
    items.sort(key=lambda x: x["viewCount"], reverse=True)
    return jsonify({"items": items}), 200


# ---------- 주간 인기(최근 N일, 기본 7일) ----------
# 예) /weekly?region=KR&q=정치&duration=any|short|long&days=7&max=50
@app.route("/weekly")
def weekly():
    region = (request.args.get("region") or "KR").upper().strip()
    q = (request.args.get("q") or "").strip()
    duration = (request.args.get("duration") or "any").lower()
    max_results = max(1, min(int(request.args.get("max", 50)), 50))
    days = int(request.args.get("days", 7))

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

    data, err = yt_get_safe("search", params)
    if err:
        return jsonify({"items": [], "error": data}), 200

    items_raw = data.get("items", [])
    video_ids = [it.get("id", {}).get("videoId") for it in items_raw if it.get("id", {}).get("videoId")]
    vc_map = fetch_view_counts(video_ids)

    items = []
    for it in items_raw:
        vid = it.get("id", {}).get("videoId")
        sn = it.get("snippet", {})
        if not vid:
            continue
        items.append({
            "title": sn.get("title"),
            "channel": sn.get("channelTitle"),
            "publishedAt": sn.get("publishedAt"),
            "thumb": sn.get("thumbnails", {}).get("medium", {}).get("url"),
            "url": f"https://www.youtube.com/watch?v={vid}",
            "viewCount": vc_map.get(vid, 0)
        })
    items.sort(key=lambda x: x["viewCount"], reverse=True)
    return jsonify({"items": items}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
