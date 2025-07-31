import requests
import xml.etree.ElementTree as ET
import os
import time
from datetime import datetime
from database import get_db_connection, get_database_config

# 設定
batch_size = 10
today = datetime.utcnow().strftime("%Y-%m-%d")

# 開啟資料庫連線
with get_db_connection() as conn:
    cursor = conn.cursor()
    config = get_database_config()

    # 找出今天榜單的新進榜遊戲（不在昨天榜單中的項目）
    cursor.execute("""
        SELECT h.objectid
        FROM hot_games h
        WHERE h.snapshot_date = %s
        AND h.objectid NOT IN (
            SELECT DISTINCT objectid 
            FROM game_detail 
            WHERE last_updated IS NOT NULL
            AND last_updated >= %s
        )
        ORDER BY h.rank
    """ if config['type'] == 'postgresql' else """
        SELECT h.objectid
        FROM hot_games h
        WHERE h.snapshot_date = ?
        AND h.objectid NOT IN (
            SELECT DISTINCT objectid 
            FROM game_detail 
            WHERE last_updated IS NOT NULL
            AND last_updated >= ?
        )
        ORDER BY h.rank
    """, (today, today))

    games_to_fetch = [row[0] for row in cursor.fetchall()]

    if not games_to_fetch:
        print("✅ 沒有需要抓取詳細資料的遊戲。")
    else:
        print(f"📊 找到 {len(games_to_fetch)} 個遊戲需要抓取詳細資料。")

        # 分批處理
        for i in range(0, len(games_to_fetch), batch_size):
            batch = games_to_fetch[i:i+batch_size]
            object_ids = ",".join(map(str, batch))
            
            print(f"🔄 處理第 {i//batch_size + 1} 批，共 {len(batch)} 個遊戲...")
            
            # 呼叫 BGG API
            url = f"https://boardgamegeek.com/xmlapi2/thing?id={object_ids}&stats=1"
            response = requests.get(url)
            
            if response.status_code != 200:
                print(f"❌ API 請求失敗: {response.status_code}")
                continue
                
            root = ET.fromstring(response.content)
            
            # 處理每個遊戲
            for item in root.findall("item"):
                objectid = int(item.attrib.get("id", 0))
                item_type = item.attrib.get("type", "")
                
                if item_type != "boardgame":
                    continue
                    
                # 基本資訊
                name_elem = item.find("name[@type='primary']")
                name = name_elem.attrib.get("value", "") if name_elem is not None else ""
                
                year_elem = item.find("yearpublished")
                year = int(year_elem.attrib.get("value", 0)) if year_elem is not None else None
                
                # 統計資料
                stats = item.find("statistics/ratings")
                if stats is not None:
                    rating = float(stats.find("average").attrib.get("value", 0))
                    
                    # BGG 排名
                    rank_elem = stats.find("ranks/rank[@type='subtype']")
                    rank = int(rank_elem.attrib.get("value", 0)) if rank_elem is not None and rank_elem.attrib.get("value", "Not Ranked") != "Not Ranked" else None
                    
                    weight = float(stats.find("averageweight").attrib.get("value", 0))
                else:
                    rating = 0
                    rank = None
                    weight = 0
                
                # 玩家人數
                minplayers_elem = item.find("minplayers")
                minplayers = int(minplayers_elem.attrib.get("value", 0)) if minplayers_elem is not None else None
                
                maxplayers_elem = item.find("maxplayers")
                maxplayers = int(maxplayers_elem.attrib.get("value", 0)) if maxplayers_elem is not None else None
                
                # 遊戲時間
                minplaytime_elem = item.find("minplaytime")
                minplaytime = int(minplaytime_elem.attrib.get("value", 0)) if minplaytime_elem is not None else None
                
                maxplaytime_elem = item.find("maxplaytime")
                maxplaytime = int(maxplaytime_elem.attrib.get("value", 0)) if maxplaytime_elem is not None else None
                
                # 圖片
                image_elem = item.find("image")
                image = image_elem.text if image_elem is not None else ""
                
                # 最佳玩家數 (這需要從 poll 中解析，這裡簡化處理)
                bestplayers = f"{minplayers}-{maxplayers}" if minplayers and maxplayers else ""
                
                # 插入或更新資料
                if config['type'] == 'postgresql':
                    cursor.execute("""
                        INSERT INTO game_detail (
                            objectid, name, year, rating, rank, weight,
                            minplayers, maxplayers, bestplayers,
                            minplaytime, maxplaytime, image, last_updated
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (objectid) DO UPDATE SET
                            name = EXCLUDED.name,
                            year = EXCLUDED.year,
                            rating = EXCLUDED.rating,
                            rank = EXCLUDED.rank,
                            weight = EXCLUDED.weight,
                            minplayers = EXCLUDED.minplayers,
                            maxplayers = EXCLUDED.maxplayers,
                            bestplayers = EXCLUDED.bestplayers,
                            minplaytime = EXCLUDED.minplaytime,
                            maxplaytime = EXCLUDED.maxplaytime,
                            image = EXCLUDED.image,
                            last_updated = EXCLUDED.last_updated
                    """, (objectid, name, year, rating, rank, weight,
                          minplayers, maxplayers, bestplayers,
                          minplaytime, maxplaytime, image, today))
                else:
                    cursor.execute("""
                        INSERT INTO game_detail (
                            objectid, name, year, rating, rank, weight,
                            minplayers, maxplayers, bestplayers,
                            minplaytime, maxplaytime, image, last_updated
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT (objectid) DO UPDATE SET
                            name = excluded.name,
                            year = excluded.year,
                            rating = excluded.rating,
                            rank = excluded.rank,
                            weight = excluded.weight,
                            minplayers = excluded.minplayers,
                            maxplayers = excluded.maxplayers,
                            bestplayers = excluded.bestplayers,
                            minplaytime = excluded.minplaytime,
                            maxplaytime = excluded.maxplaytime,
                            image = excluded.image,
                            last_updated = excluded.last_updated
                    """, (objectid, name, year, rating, rank, weight,
                          minplayers, maxplayers, bestplayers,
                          minplaytime, maxplaytime, image, today))
                
                print(f"✅ 已更新遊戲: {name} ({objectid})")
            
            # 提交這個批次
            conn.commit()
            
            # API 限制：每次請求間隔
            time.sleep(1)

        print(f"✅ 完成詳細資料抓取，共處理 {len(games_to_fetch)} 個遊戲。")