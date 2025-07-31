import requests
import xml.etree.ElementTree as ET
from datetime import datetime
import os
from database import get_db_connection, get_database_config

# 資料庫與儲存設定
snapshot_date = datetime.utcnow().strftime("%Y-%m-%d")
url = "https://boardgamegeek.com/xmlapi2/hot?type=boardgame"

# 建立資料夾
os.makedirs("data", exist_ok=True)
os.makedirs("data/cache", exist_ok=True)

# 抓取熱門榜單
response = requests.get(url)
root = ET.fromstring(response.content)

# 開啟資料庫
with get_db_connection() as conn:
    cursor = conn.cursor()
    
    # 取得資料庫類型
    config = get_database_config()
    
    # 儲存資料
    for item in root.findall("item"):
        rank = int(item.attrib.get("rank", 0))
        objectid = int(item.attrib.get("id", 0))
        name = item.find("name").attrib.get("value") if item.find("name") is not None else ""
        year = int(item.find("yearpublished").attrib.get("value", 0)) if item.find("yearpublished") is not None else None
        thumbnail = item.find("thumbnail").attrib.get("value") if item.find("thumbnail") is not None else ""

        if config['type'] == 'postgresql':
            # PostgreSQL 使用 ON CONFLICT
            cursor.execute("""
                INSERT INTO hot_games (snapshot_date, rank, objectid, name, year, thumbnail)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT(snapshot_date, rank) DO UPDATE SET
                    objectid=EXCLUDED.objectid,
                    name=EXCLUDED.name,
                    year=EXCLUDED.year,
                    thumbnail=EXCLUDED.thumbnail
            """, (snapshot_date, rank, objectid, name, year, thumbnail))
        else:
            # SQLite 使用 ON CONFLICT
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

print(f"✅ 抓取並儲存熱門桌遊榜單，共 {len(root.findall('item'))} 筆資料。")