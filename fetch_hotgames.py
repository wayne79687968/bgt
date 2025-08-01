import requests
import xml.etree.ElementTree as ET
from datetime import datetime
import os
from database import get_db_connection, get_database_config, init_database

# 確保數據庫已初始化
print("🗃️ 確保數據庫已初始化...")
try:
    init_database()
    print("✅ 數據庫初始化完成")
except Exception as e:
    print(f"❌ 數據庫初始化失敗: {e}")
    exit(1)

# 資料庫與儲存設定
snapshot_date = datetime.utcnow().strftime("%Y-%m-%d")
url = "https://boardgamegeek.com/xmlapi2/hot?type=boardgame"

print(f"📅 快照日期: {snapshot_date}")
print(f"🌐 BGG API URL: {url}")

# 建立資料夾
print("📁 創建必要目錄...")
os.makedirs("data", exist_ok=True)
os.makedirs("data/cache", exist_ok=True)
print("✅ 目錄創建完成")

# 抓取熱門榜單
print("🌐 開始抓取 BGG 熱門榜單...")
import time
api_start_time = time.time()

try:
    response = requests.get(url, timeout=30)
    api_time = time.time() - api_start_time
    print(f"✅ API 請求完成 (耗時: {api_time:.2f}秒，狀態碼: {response.status_code})")

    if response.status_code != 200:
        print(f"❌ API 請求失敗: {response.status_code}")
        exit(1)

    print(f"📄 響應內容長度: {len(response.content)} 字節")

except Exception as e:
    api_time = time.time() - api_start_time
    print(f"❌ API 請求失敗 (耗時: {api_time:.2f}秒): {e}")
    exit(1)

print("🔍 開始解析 XML 響應...")
parse_start_time = time.time()

try:
    root = ET.fromstring(response.content)
    parse_time = time.time() - parse_start_time
    print(f"✅ XML 解析完成 (耗時: {parse_time:.2f}秒)")

    # 統計遊戲數量
    items = root.findall('item')
    print(f"🎲 發現 {len(items)} 款熱門遊戲")

except Exception as e:
    parse_time = time.time() - parse_start_time
    print(f"❌ XML 解析失敗 (耗時: {parse_time:.2f}秒): {e}")
    exit(1)

# 開啟資料庫
print("🔗 開始保存到數據庫...")
db_start_time = time.time()

with get_db_connection() as conn:
    cursor = conn.cursor()
    config = get_database_config()

    print("🗑️ 清理舊數據...")
    # 先刪除今天的舊資料（如果有的話）
    if config['type'] == 'postgresql':
        cursor.execute("DELETE FROM hot_games WHERE snapshot_date = %s", (snapshot_date,))
    else:
        cursor.execute("DELETE FROM hot_games WHERE snapshot_date = ?", (snapshot_date,))

    deleted_count = cursor.rowcount
    print(f"🗑️ 清理了 {deleted_count} 筆舊數據")

    print("💾 開始插入新數據...")
    inserted_count = 0

    # 儲存資料
    for item in root.findall("item"):
        rank = int(item.attrib.get("rank", 0))
        objectid = int(item.attrib.get("id", 0))
        name = item.find("name").attrib.get("value") if item.find("name") is not None else ""
        year = int(item.find("yearpublished").attrib.get("value", 0)) if item.find("yearpublished") is not None else None
        thumbnail = item.find("thumbnail").attrib.get("value") if item.find("thumbnail") is not None else ""

        # 每 10 筆輸出一次進度
        if inserted_count % 10 == 0:
            print(f"💾 正在插入第 {inserted_count + 1} 筆數據...")

        try:
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

            inserted_count += 1

        except Exception as e:
            print(f"❌ 插入數據失敗 (排名 {rank}, ID {objectid}): {e}")
            continue

    print("💾 開始提交到數據庫...")
    commit_start_time = time.time()
    try:
        conn.commit()
        commit_time = time.time() - commit_start_time
        print(f"✅ 數據庫提交成功 (耗時: {commit_time:.2f}秒)")
    except Exception as e:
        commit_time = time.time() - commit_start_time
        print(f"❌ 數據庫提交失敗 (耗時: {commit_time:.2f}秒): {e}")
        exit(1)

    db_time = time.time() - db_start_time
    print(f"✅ 數據庫操作完成 (總耗時: {db_time:.2f}秒)")

total_time = time.time() - api_start_time
print("=" * 60)
print(f"🎉 FETCH_HOTGAMES.PY 執行完成！")
print(f"📊 成功處理 {inserted_count} 款熱門遊戲")
print(f"📅 快照日期: {snapshot_date}")
print(f"⏱️ 總執行時間: {total_time:.2f}秒")
print("=" * 60)