from flask import Flask, request, jsonify, send_from_directory
import os
import requests

app = Flask(__name__, static_url_path="", static_folder="static")

# Render 환경변수에서 키 읽기
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

# 헬스체크 (옵션)
@app.route("/health")
def health():
    return "ok", 200

# 루트: static/index.html 있으면 그걸 서빙, 없으면 안내 문구
@app.route("/")
def home():
    index_path = os.path.join(app.static_folder or "", "index.html")
    if os.path.isfile(index_path):
        return send_from_directory("static", "index.html")
    return (
        "Flask is running on Render 🎉<br>"
        "검색 예: <code>/search?q=축구</code>"
    )

# 유튜브 검색 API (간단 버전)
@app.route("/search")
def search():
    if not YOUTUBE_API_KEY:
        return jsonify({"error": "YOUTUBE_API_KEY is not set on the server."}), 500

    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "쿼리 파라미터 q가 필요합니다. 예: /search?q=쇼핑"}), 400

    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "key": YOUTUBE_API_KEY,
        "part": "snippet",
        "q": q,
        "type": "video",
        "maxResults": 10,
        "order": "viewCount"
    }
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()

    items = []
    for it in r.json().get("items", []):
        vid = it["id"]["videoId"]
        items.append({
            "title": it["snippet"]["title"],
            "channel": it["snippet"]["channelTitle"],
            "publishedAt": it["snippet"]["publishedAt"],
            "url": f"https://www.youtube.com/watch?v={vid}"
        })
    return jsonify({"items": items})

if __name__ == "__main__":
    # 로컬 실행용 (Render에서는 gunicorn이 실행)
    app.run(host="0.0.0.0", port=5000, debug=True)
