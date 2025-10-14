import requests
import xml.etree.ElementTree as ET
import os
from utils.common import setup_logging
import time
from datetime import datetime
import pytz
from database import get_db_connection, get_database_config, init_database

# 數據庫初始化由 scheduler.py 負責，這裡不需要重複調用以避免並發問題
print("🗃️ [FETCH_DETAILS] 跳過數據庫初始化（由 scheduler.py 負責）")
print(f"🗃️ [FETCH_DETAILS] 當前時間: {datetime.utcnow().strftime('%H:%M:%S')}")
print("🗃️ [FETCH_DETAILS] 開始主要處理...")

# 設定
batch_size = 10
# 使用台北時區獲取當前日期
taipei_tz = pytz.timezone('Asia/Taipei')
today = datetime.now(taipei_tz).strftime("%Y-%m-%d")

# 開啟資料庫連線
setup_logging()
print("🔗 開始處理遊戲詳細資料...")
with get_db_connection() as conn:
    cursor = conn.cursor()
    config = get_database_config()

    print(f"📅 目標日期: {today}")
    print("🔍 開始查詢需要抓取詳細資料的遊戲...")

    import time
    query_start_time = time.time()

    # 找出今天榜單的新進榜遊戲（不在昨天榜單中的項目）- PostgreSQL 單一路徑
    query = """
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
    """
    params = (today, today)

    print(f"📋 執行查詢: {query[:100]}...")
    print(f"📋 查詢參數: {params}")

    try:
        cursor.execute(query, params)
        query_time = time.time() - query_start_time
        print(f"✅ 查詢執行成功 (耗時: {query_time:.2f}秒)")

        print("📊 正在獲取查詢結果...")
        fetch_start_time = time.time()
        games_to_fetch = [row[0] for row in cursor.fetchall()]
        fetch_time = time.time() - fetch_start_time
        print(f"✅ 結果獲取完成 (耗時: {fetch_time:.2f}秒)")

    except Exception as e:
        query_time = time.time() - query_start_time
        print(f"❌ 查詢執行失敗 (耗時: {query_time:.2f}秒): {e}")
        import traceback
        traceback.print_exc()
        exit(1)

    if not games_to_fetch:
        print("✅ 沒有需要抓取詳細資料的遊戲。")
    else:
        print(f"📊 找到 {len(games_to_fetch)} 個遊戲需要抓取詳細資料。")
        print(f"🎮 遊戲 ID 列表: {games_to_fetch[:10]}{'...' if len(games_to_fetch) > 10 else ''}")

        # 分批處理
        total_batches = (len(games_to_fetch) + batch_size - 1) // batch_size
        print(f"📦 將分 {total_batches} 批處理，每批 {batch_size} 個遊戲")

        for i in range(0, len(games_to_fetch), batch_size):
            batch = games_to_fetch[i:i+batch_size]
            object_ids = ",".join(map(str, batch))
            batch_num = i//batch_size + 1

            print(f"🔄 處理第 {batch_num}/{total_batches} 批，共 {len(batch)} 個遊戲...")
            print(f"🎲 本批遊戲 ID: {batch}")

            # 呼叫 BGG API
            print(f"🌐 正在請求 BGG API...")
            api_start_time = time.time()
            url = f"https://boardgamegeek.com/xmlapi2/thing?id={object_ids}&stats=1"
            print(f"🔗 API URL: {url}")

            try:
                response = requests.get(url, timeout=30)
                api_time = time.time() - api_start_time
                print(f"✅ API 請求完成 (耗時: {api_time:.2f}秒，狀態碼: {response.status_code})")
            except Exception as e:
                api_time = time.time() - api_start_time
                print(f"❌ API 請求失敗 (耗時: {api_time:.2f}秒): {e}")
                continue

            if response.status_code != 200:
                print(f"❌ API 請求失敗: {response.status_code}")
                continue

            print(f"📄 響應內容長度: {len(response.content)} 字節")
            print("🔍 開始解析 XML 響應...")

            try:
                parse_start_time = time.time()
                root = ET.fromstring(response.content)
                parse_time = time.time() - parse_start_time
                print(f"✅ XML 解析完成 (耗時: {parse_time:.2f}秒)")
            except Exception as e:
                print(f"❌ XML 解析失敗: {e}")
                continue

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

                # 提取分類、機制、設計師、美術、發行商資訊
                def extract_links(item, link_type):
                    """從 XML 中提取指定類型的連結資訊"""
                    links = item.findall(f"link[@type='{link_type}']")
                    return ", ".join([link.attrib.get("value", "") for link in links if link.attrib.get("value")])

                categories = extract_links(item, "boardgamecategory")
                mechanics = extract_links(item, "boardgamemechanic")
                designers = extract_links(item, "boardgamedesigner")
                artists = extract_links(item, "boardgameartist")
                publishers = extract_links(item, "boardgamepublisher")

                print(f"📋 {name} 詳細資訊:")
                print(f"  分類: {categories[:50]}{'...' if len(categories) > 50 else ''}")
                print(f"  機制: {mechanics[:50]}{'...' if len(mechanics) > 50 else ''}")
                print(f"  設計師: {designers[:30]}{'...' if len(designers) > 30 else ''}")

                # 插入或更新資料
                cursor.execute("""
                    INSERT INTO game_detail (
                        objectid, name, year, rating, rank, weight,
                        minplayers, maxplayers, bestplayers,
                        minplaytime, maxplaytime,
                        categories, mechanics, designers, artists, publishers,
                        image, last_updated
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                        categories = EXCLUDED.categories,
                        mechanics = EXCLUDED.mechanics,
                        designers = EXCLUDED.designers,
                        artists = EXCLUDED.artists,
                        publishers = EXCLUDED.publishers,
                        image = EXCLUDED.image,
                        last_updated = EXCLUDED.last_updated
                """, (objectid, name, year, rating, rank, weight,
                      minplayers, maxplayers, bestplayers,
                      minplaytime, maxplaytime,
                      categories, mechanics, designers, artists, publishers,
                      image, today))

                print(f"✅ 已更新遊戲: {name} ({objectid})")

            # 提交這個批次
            conn.commit()

            # API 限制：每次請求間隔
            time.sleep(1)

        print(f"✅ 完成詳細資料抓取，共處理 {len(games_to_fetch)} 個遊戲。")