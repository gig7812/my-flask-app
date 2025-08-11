from flask import Flask, render_template, request, jsonify
import os
import requests

app = Flask(__name__, template_folder="templates")

# Render 대시보드(Environment)에 넣은 키를 읽음
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

@app.route("/health")
def health():
    return "ok", 200

@app.route("/")
def index():
    # / 접속 시 UI 페이지
    return render_template("index.html")

@app.route("/search")
def search():
    # 예: /search?q=쇼핑
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
        "maxResults": 10
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
            "url": f"https://www.youtube.com/watch?v={vid}"
        })
    return jsonify({"items": items})

if __name__ == "__main__":
    # 로컬 실행용 (Render에선 Procfile의 gunicorn이 실행)
    app.run(host="0.0.0.0", port=5000, debug=True)
