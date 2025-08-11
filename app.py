from flask import Flask, request, jsonify, send_from_directory
import os
import requests

# static 폴더를 루트(`/`)에서 서빙
app = Flask(__name__, static_url_path="", static_folder="static")

# Render(Environment)에서 넣어둔 키
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

# 헬스체크
@app.route("/health")
def health():
    return "ok", 200

# 루트 → static/index.html 반환
@app.route("/")
def home():
    return send_from_directory("static", "index.html")

# 유튜브 검색 API (프론트에서 fetch로 호출)
@app.route("/search")
def search():
    # 키가 없으면 바로 에러 반환
    if not YOUTUBE_API_KEY:
        return jsonify({"error": "YOUTUBE_API_KEY is not set on server"}), 500

    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"items": []})

    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "key": YOUTUBE_API_KEY,
        "part": "snippet",
        "q": q,
        "type": "video",
        "order": "viewCount",
        "maxResults": 10
    }

    try:
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
    except requests.RequestException as e:
        return jsonify({"error": f"youtube api error: {e}"}), 502

    data = r.json()
    items = []
    for it in data.get("items", []):
        vid = it["id"]["videoId"]
        sn = it["snippet"]
        items.append({
            "title": sn["title"],
            "channel": sn["channelTitle"],
            "publishedAt": sn["publishedAt"],
            "thumb": sn["thumbnails"]["medium"]["url"],
            "url": f"https://www.youtube.com/watch?v={vid}"
        })
    return jsonify({"items": items})

if __name__ == "__main__":
    # 로컬 테스트용 (Render에선 Procfile의 gunicorn이 실행됨)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
