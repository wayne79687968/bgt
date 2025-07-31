import requests
import xml.etree.ElementTree as ET
import sqlite3
import os
import time
from datetime import datetime

# 設定
db_path = "data/bgg_rag.db"
batch_size = 10
today = datetime.utcnow().strftime("%Y-%m-%d")

# 開啟資料庫連線
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# 找出今天榜單的新進榜遊戲（不在昨天榜單中的項目）
cursor.execute("""
    SELECT h.objectid
    FROM hot_games h
    WHERE h.snapshot_date = ?
    AND h.objectid NOT IN (
        SELECT objectid FROM hot_games WHERE snapshot_date < ? AND objectid IS NOT NULL
    )
""", (today, today))
new_ids = [str(row[0]) for row in cursor.fetchall()]
print(f"共 {len(new_ids)} 款新進榜遊戲。")

# 分批查詢並寫入快取
def fetch_details(id_batch):
    ids = ",".join(id_batch)
    url = f"https://boardgamegeek.com/xmlapi2/thing?id={ids}&stats=1"
    response = requests.get(url)
    while response.status_code == 202:
        print("等待 BGG API 處理中...")
        time.sleep(2)
        response = requests.get(url)
    return ET.fromstring(response.content)

def get_attrs(elem, path, attr="value"):
    return [e.attrib[attr] for e in elem.findall(path)]

def get_attrs_with_ids(elem, path, name_attr="value", id_attr="id"):
    elements = elem.findall(path)
    names = [e.attrib[name_attr] for e in elements]
    ids = [e.attrib[id_attr] for e in elements]
    return names, ids

for i in range(0, len(new_ids), batch_size):
    batch = new_ids[i:i + batch_size]
    root = fetch_details(batch)
    for item in root.findall("item"):
        objectid = int(item.attrib["id"])
        name_elem = item.find("name[@type='primary']")
        name = name_elem.attrib["value"] if name_elem is not None else f"Boardgame {objectid}"
        year = int(item.find("yearpublished").attrib["value"]) if item.find("yearpublished") is not None else None
        rating = float(item.find(".//average").attrib["value"]) if item.find(".//average") is not None else None
        rank_node = item.find(".//rank[@name='boardgame']")
        rank = int(rank_node.attrib["value"]) if rank_node is not None and rank_node.attrib["value"].isdigit() else None
        weight = float(item.find(".//averageweight").attrib["value"]) if item.find(".//averageweight") is not None else None
        minplayers = int(item.find("minplayers").attrib["value"]) if item.find("minplayers") is not None else None
        maxplayers = int(item.find("maxplayers").attrib["value"]) if item.find("maxplayers") is not None else None
        minplaytime = int(item.find("minplaytime").attrib["value"]) if item.find("minplaytime") is not None else None
        maxplaytime = int(item.find("maxplaytime").attrib["value"]) if item.find("maxplaytime") is not None else None

        # 擷取最佳人數
        poll_summary = item.find(".//poll-summary[@name='suggested_numplayers']")
        bestplayers = ""
        if poll_summary is not None:
            best = poll_summary.find("result[@name='bestwith']")
            if best is not None:
                bestplayers = best.attrib["value"].replace("Best with", "").replace("players", "").strip()

        categories = ", ".join(get_attrs(item, "link[@type='boardgamecategory']"))
        mechanics = ", ".join(get_attrs(item, "link[@type='boardgamemechanic']"))
        designers = ", ".join(get_attrs(item, "link[@type='boardgamedesigner']"))
        artists = ", ".join(get_attrs(item, "link[@type='boardgameartist']"))
        publishers = ", ".join(get_attrs(item, "link[@type='boardgamepublisher']"))
        
        # 獲取對應的ID資訊
        category_names, category_ids = get_attrs_with_ids(item, "link[@type='boardgamecategory']")
        mechanic_names, mechanic_ids = get_attrs_with_ids(item, "link[@type='boardgamemechanic']")
        designer_names, designer_ids = get_attrs_with_ids(item, "link[@type='boardgamedesigner']")
        artist_names, artist_ids = get_attrs_with_ids(item, "link[@type='boardgameartist']")
        publisher_names, publisher_ids = get_attrs_with_ids(item, "link[@type='boardgamepublisher']")
        image = item.find("image").text if item.find("image") is not None else ""

        # 儲存遊戲基本資料
        cursor.execute("""
            INSERT INTO game_detail (
                objectid, name, year, rating, rank, weight,
                minplayers, maxplayers, bestplayers,
                minplaytime, maxplaytime,
                categories, mechanics, designers, artists, publishers,
                image, last_updated
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(objectid) DO UPDATE SET
                name=excluded.name,
                year=excluded.year,
                rating=excluded.rating,
                rank=excluded.rank,
                weight=excluded.weight,
                minplayers=excluded.minplayers,
                maxplayers=excluded.maxplayers,
                bestplayers=excluded.bestplayers,
                minplaytime=excluded.minplaytime,
                maxplaytime=excluded.maxplaytime,
                categories=excluded.categories,
                mechanics=excluded.mechanics,
                designers=excluded.designers,
                artists=excluded.artists,
                publishers=excluded.publishers,
                image=excluded.image,
                last_updated=excluded.last_updated
        """, (
            objectid, name, year, rating, rank, weight,
            minplayers, maxplayers, bestplayers,
            minplaytime, maxplaytime,
            categories, mechanics, designers, artists, publishers,
            image, datetime.utcnow().isoformat()
        ))

        # 儲存分類資料和關聯
        def store_categories(names, ids, category_type):
            # 清除舊的關聯
            cursor.execute("""
                DELETE FROM game_categories 
                WHERE objectid = ? AND category_type = ?
            """, (objectid, category_type))
            
            # 儲存新的分類和關聯
            for name, cat_id in zip(names, ids):
                # 儲存分類資料（如果不存在）
                cursor.execute("""
                    INSERT OR IGNORE INTO bgg_items (id, name, category)
                    VALUES (?, ?, ?)
                """, (int(cat_id), name, category_type))
                
                # 儲存遊戲與分類的關聯
                cursor.execute("""
                    INSERT OR IGNORE INTO game_categories (objectid, category_id, category_type)
                    VALUES (?, ?, ?)
                """, (objectid, int(cat_id), category_type))

        # 儲存各種分類
        store_categories(category_names, category_ids, 'boardgamecategory')
        store_categories(mechanic_names, mechanic_ids, 'boardgamemechanic')
        store_categories(designer_names, designer_ids, 'boardgamedesigner')
        store_categories(artist_names, artist_ids, 'boardgameartist')
        store_categories(publisher_names, publisher_ids, 'boardgamepublisher')

conn.commit()
conn.close()
print("✅ 已完成詳細資料查詢與修正快取。")
