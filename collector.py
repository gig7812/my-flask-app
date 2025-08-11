# collector.py
import os
import datetime as dt
import requests
import psycopg2

YOUTUBE_API_KEY = os.environ["YOUTUBE_API_KEY"]
DATABASE_URL = os.environ["DATABASE_URL"]
YT_BASE = "https://www.googleapis.com/youtube/v3"

REGIONS = [r.strip().upper() for r in os.getenv("REGIONS", "KR").split(",") if r.strip()]
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "50"))  # 1~50


def yt_get(path, params):
    p = dict(params or {})
    p["key"] = YOUTUBE_API_KEY
    r = requests.get(f"{YT_BASE}/{path}", params=p, timeout=20)
    r.raise_for_status()
    return r.json()


def fetch_trending(region="KR", max_results=50):
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
            "video_id": vid,
            "title": sn.get("title", ""),
            "channel": sn.get("channelTitle", ""),
            "thumb": sn.get("thumbnails", {}).get("medium", {}).get("url"),
            "view_count": int(st.get("viewCount", 0)),
        })
    return items


def ensure_schema(conn):
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS video_snapshots (
      video_id   TEXT NOT NULL,
      region     TEXT NOT NULL,
      ts         TIMESTAMPTZ NOT NULL,
      view_count BIGINT NOT NULL,
      title      TEXT,
      channel    TEXT,
      thumb      TEXT,
      PRIMARY KEY (video_id, ts)
    );
    """)
    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_video_snapshots_region_ts
      ON video_snapshots (region, ts DESC);
    """)
    conn.commit()
    cur.close()


def store_snapshots(region="KR"):
    items = fetch_trending(region, max_results=min(MAX_RESULTS, 50))
    ts = dt.datetime.utcnow()
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    ensure_schema(conn)
    cur = conn.cursor()
    for it in items:
        cur.execute("""
        INSERT INTO video_snapshots
          (video_id, region, ts, view_count, title, channel, thumb)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING;
        """, (it["video_id"], region, ts, it["view_count"], it["title"], it["channel"], it["thumb"]))
    conn.commit()
    cur.close()
    conn.close()


if __name__ == "__main__":
    for r in REGIONS:
        store_snapshots(r)
