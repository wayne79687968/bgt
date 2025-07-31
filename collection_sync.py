import requests
import xml.etree.ElementTree as ET
from datetime import datetime
import os
import time
from database import get_db_connection, get_database_config

def execute_query(cursor, query, params, config_type):
    """執行相容性查詢"""
    if config_type == 'postgresql':
        query_pg = query.replace('?', '%s')
        cursor.execute(query_pg, params)
    else:
        cursor.execute(query, params)

# 用戶設定
username = "wayne79687968"
os.makedirs("data", exist_ok=True)

# API URL
url = f"https://boardgamegeek.com/xmlapi2/collection?username={username}&subtype=boardgame&excludesubtype=boardgameexpansion&stats=1"

# 等待 BGG 準備好資料（可能返回 202）
response = requests.get(url)
while response.status_code == 202:
    print("BGG 回傳 202，等待中...")
    time.sleep(2)
    response = requests.get(url)

# 解析 XML
root = ET.fromstring(response.content)

# 連線到資料庫
with get_db_connection() as conn:
    cursor = conn.cursor()
    config = get_database_config()

    # 建立資料表（若尚未存在）
    if config['type'] == 'postgresql':
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS collection (
            objectid INTEGER PRIMARY KEY,
            name TEXT,
            status TEXT,
            rating REAL,
            wish_priority INTEGER,
            last_sync TIMESTAMP
        )
        """)
    else:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS collection (
            objectid INTEGER PRIMARY KEY,
            name TEXT,
            status TEXT,
            rating REAL,
            wish_priority INTEGER,
            last_sync TIMESTAMP
        )
        """)

    # 當前時間
    now = datetime.utcnow().isoformat()

    # 同步資料
    for item in root.findall("item"):
        objectid = int(item.attrib.get("objectid", 0))
        name = item.find("name").text if item.find("name") is not None else ""
        rating_elem = item.find(".//rating")
        rating = float(rating_elem.attrib["value"]) if rating_elem is not None and rating_elem.attrib["value"] != "N/A" else None
        status_elem = item.find("status")
        status = []
        if status_elem is not None:
            for key in status_elem.attrib:
                if status_elem.attrib[key] == "1":
                    status.append(key)
        status_str = ", ".join(status)
        wish_priority = int(item.find("wishlistpriority").text) if item.find("wishlistpriority") is not None else None

        if config['type'] == 'postgresql':
            cursor.execute("""
                INSERT INTO collection (objectid, name, status, rating, wish_priority, last_sync)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT(objectid) DO UPDATE SET
                    name=EXCLUDED.name,
                    status=EXCLUDED.status,
                    rating=EXCLUDED.rating,
                    wish_priority=EXCLUDED.wish_priority,
                    last_sync=EXCLUDED.last_sync
            """, (objectid, name, status_str, rating, wish_priority, now))
        else:
            cursor.execute("""
                INSERT INTO collection (objectid, name, status, rating, wish_priority, last_sync)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(objectid) DO UPDATE SET
                    name=excluded.name,
                    status=excluded.status,
                    rating=excluded.rating,
                    wish_priority=excluded.wish_priority,
                    last_sync=excluded.last_sync
            """, (objectid, name, status_str, rating, wish_priority, now))

    conn.commit()

print(f"✅ 成功同步收藏清單，共 {len(root.findall('item'))} 筆資料。")