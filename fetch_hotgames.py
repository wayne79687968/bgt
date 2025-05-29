import requests
import xml.etree.ElementTree as ET
import sqlite3
from datetime import datetime
import os

# 資料庫與儲存設定
db_path = "data/bgg_rag.db"
snapshot_date = datetime.utcnow().strftime("%Y-%m-%d")
url = "https://boardgamegeek.com/xmlapi2/hot?type=boardgame"

# 建立資料夾
os.makedirs("data", exist_ok=True)
os.makedirs("data/cache", exist_ok=True)

# 抓取熱門榜單
response = requests.get(url)
root = ET.fromstring(response.content)

# 開啟資料庫
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# 儲存資料
for item in root.findall("item"):
    rank = int(item.attrib.get("rank", 0))
    objectid = int(item.attrib.get("id", 0))
    name = item.find("name").attrib.get("value") if item.find("name") is not None else ""
    year = int(item.find("yearpublished").attrib.get("value", 0)) if item.find("yearpublished") is not None else None
    thumbnail = item.find("thumbnail").attrib.get("value") if item.find("thumbnail") is not None else ""

    cursor.execute("""
        INSERT INTO hot_games (snapshot_date, rank, objectid, name, year, thumbnail)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(snapshot_date, rank) DO UPDATE SET
            objectid=excluded.objectid,
            name=excluded.name,
            year=excluded.year,
            thumbnail=excluded.thumbnail
    """, (snapshot_date, rank, objectid, name, year, thumbnail))

conn.commit()
conn.close()
print(f"✅ 抓取並儲存熱門桌遊榜單，共 {len(root.findall('item'))} 筆資料。")
