from flask import Flask, render_template, request, jsonify
import os
import requests

app = Flask(__name__)

# 환경변수에서 API 키 불러오기
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

@app.route("/")
def index():
    return "Hello, Flask is running with Render!"

# 유튜브 검색 API 예시 엔드포인트
@app.route("/search")
def search():
    query = request.args.get("q")
    if not query:
        return jsonify({"error": "검색어(q)가 필요합니다"}), 400

    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part": "snippet",
        "q": query,
        "key": YOUTUBE_API_KEY,
        "maxResults": 5
    }
    response = requests.get(url, params=params)
    return jsonify(response.json())

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
