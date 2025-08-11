from flask import Flask, request, jsonify, send_from_directory
import os
import requests

# static/index.html을 루트로 서빙
app = Flask(__name__, static_url_path="", static_folder="static")

# Render 환경변수에서 YouTube API 키 읽기
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

# 헬스체크(선택)
@app.route("/health")
def health():
    return "ok", 200

# 루트: static/index.html 제공
@app.route("/")
def home():
    return send_from_directory("static", "index.html")

# 간단 검색 API: /search?q=키워드
@app.route("/search")
def search():
    if not YOUTUBE_API_KEY:
        return jsonify({"error": "서버 환경변수 YOUTUBE_API_KEY가 설정되지 않았습니다."}), 500

    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"error": "검색어(q)가 필요합니다. 예: /search?q=쇼핑"}), 400

    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "key": YOUTUBE_API_KEY,
        "part": "snippet",
        "q": q,
        "type": "video",
        "order": "viewCount",
        "maxResults": 10,
    }

    try:
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
    except requests.RequestException as e:
        return jsonify({"error": f"유튜브 API 호출 실패: {e}"}), 502

    items = []
    for it in r.json().get("items", []):
        vid = it["id"]["videoId"]
        sn = it["snippet"]
        items.append({
            "title": sn["title"],
            "channel": sn["channelTitle"],
            "publishedAt": sn["publishedAt"],
            "thumb": sn["thumbnails"]["medium"]["url"],
            "url": f"https://www.youtube.com/watch?v={vid}",
        })
    return jsonify({"items": items})

if __name__ == "__main__":
    # 로컬 테스트용 (Render에선 Procfile의 gunicorn이 실행됨)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
