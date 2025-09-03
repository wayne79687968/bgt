#!/usr/bin/env python3
import os
from datetime import datetime, date
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from dotenv import load_dotenv
import subprocess
import sys
import logging
import glob
import re
import json
import requests
from bs4 import BeautifulSoup
from database import get_db_connection, get_database_config, execute_query
# 認證系統導入 - 優先使用 email_auth，Google 認證為可選
from email_auth import EmailAuth, login_required, admin_required, full_access_required, has_full_access, get_current_user

# 嘗試導入 Google 認證 (可選)
try:
    from google_auth import GoogleAuth
    GOOGLE_AUTH_AVAILABLE = True
except ImportError:
    GoogleAuth = None
    GOOGLE_AUTH_AVAILABLE = False
import threading
import time

# 進階推薦系統
try:
    from advanced_recommender import AdvancedBoardGameRecommender
    ADVANCED_RECOMMENDER_AVAILABLE = True
except ImportError as e:
    logging.warning(f"進階推薦系統無法載入: {e}")
    ADVANCED_RECOMMENDER_AVAILABLE = False

# 全域任務狀態追蹤
task_status = {
    'is_running': False,
    'start_time': None,
    'current_step': '',
    'progress': 0,
    'message': '',
    'last_update': None,
    'stop_requested': False,
    'stopped_by_user': False
}

def update_task_status(step, progress, message):
    """更新任務狀態"""
    global task_status
    task_status.update({
        'current_step': step,
        'progress': progress,
        'message': message,
        'last_update': datetime.now()
    })
    logger.info(f"📊 任務進度: {progress}% - {step} - {message}")

def request_task_stop():
    """請求停止當前任務"""
    global task_status
    if task_status['is_running']:
        task_status['stop_requested'] = True
        logger.info("🛑 用戶請求停止任務")
        return True
    return False

def parse_execution_progress(line, elapsed):
    """解析執行輸出，返回進度和狀態訊息"""
    line = line.strip()

    # 步驟1: 抓取熱門遊戲榜單
    if "抓取熱門桌遊榜單" in line or "找到" in line and "個遊戲" in line:
        if "完成詳細資料抓取" in line:
            return 20, f"✅ 步驟1完成: {line}"
        return 15, f"📊 步驟1/4: {line}"

    # 步驟2: 抓取遊戲詳細資訊
    elif "處理第" in line and "批" in line:
        return 25, f"🎲 步驟2/4: {line}"
    elif "已更新遊戲:" in line:
        game_name = line.split("已更新遊戲:")[-1].split("(")[0].strip() if "已更新遊戲:" in line else ""
        return 30, f"🎮 步驟2/4: 已更新 {game_name}"
    elif "完成詳細資料抓取" in line:
        return 40, f"✅ 步驟2完成: {line}"

    # 步驟3: 抓取討論串
    elif "開始抓取遊戲的討論串" in line:
        game_name = line.split(":")[-1].strip() if ":" in line else "遊戲"
        return 45, f"💬 步驟3/4: 開始抓取 {game_name} 的討論串"
    elif "抓取討論串列表" in line:
        return 50, f"📋 步驟3/4: {line}"
    elif "抓取討論串文章內容" in line:
        return 55, f"📝 步驟3/4: {line}"
    elif "翻譯討論串" in line or "翻譯完成" in line:
        game_name = ""
        if "翻譯討論串" in line:
            parts = line.split()
            for i, part in enumerate(parts):
                if "翻譯討論串" in part and i > 0:
                    game_name = parts[i-1]
                    break
        return 70, f"🌍 步驟3/4: 正在翻譯 {game_name}".strip()
    elif "處理完成遊戲" in line:
        game_name = line.split(":")[-1].strip() if ":" in line else ""
        return 75, f"✅ 步驟3進度: 已完成 {game_name}"

    # 步驟4: 產生報表
    elif "開始產生" in line and "報表" in line:
        return 80, f"📄 步驟4/4: {line}"
    elif "已產出" in line and "報告" in line:
        return 95, f"✅ 步驟4完成: {line}"
    elif "報表產生完成" in line:
        return 100, f"🎉 任務完成: {line}"

    # 資料庫相關訊息
    elif "數據庫" in line or "資料庫" in line:
        if "初始化" in line:
            return 5, f"🗃️ 初始化: {line}"
        return None, f"🗃️ 資料庫: {line}"

    # 錯誤訊息
    elif "錯誤" in line or "失敗" in line or "❌" in line:
        return None, f"⚠️ {line}"

    # 其他重要訊息
    elif any(keyword in line for keyword in ["✅", "📊", "🎲", "💬", "📋", "📝", "🌍", "📄"]):
        return None, line

    # 預設情況：顯示原始訊息但不更新進度
    return None, line if line else None

def reset_task_status():
    """重置任務狀態"""
    global task_status
    task_status.update({
        'is_running': False,
        'start_time': None,
        'current_step': '',
        'progress': 0,
        'message': '',
        'last_update': None,
        'stop_requested': False,
        'stopped_by_user': False
    })

def check_if_should_stop():
    """檢查是否應該停止任務"""
    return task_status.get('stop_requested', False)

# 嘗試導入 markdown，如果失敗則使用簡單的文字顯示
try:
    import markdown
    MARKDOWN_AVAILABLE = True
except ImportError:
    MARKDOWN_AVAILABLE = False
    print("Warning: markdown module not available. Reports will be displayed as plain text.")

# 載入環境變數
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key-here')

# 設定日誌
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 認證系統設定
email_auth = EmailAuth()

# Google OAuth 設定 (可選)
google_auth = GoogleAuth() if GOOGLE_AUTH_AVAILABLE else None

# 資料庫初始化狀態追蹤
_db_initialized = False

def force_db_initialization():
    """強制執行資料庫初始化，用於應用啟動"""
    global _db_initialized
    
    if _db_initialized:
        print("✓ 資料庫已初始化，跳過重複初始化")
        return True
    
    print("🔄 強制執行資料庫初始化...")
    try:
        from database import init_database
        config = get_database_config()
        print(f"🗃️ 強制初始化 {config['type']} 資料庫結構...")
        init_database()
        print(f"✅ {config['type']} 資料庫強制初始化完成")
        _db_initialized = True
        return True
    except Exception as e:
        print(f"❌ 強制資料庫初始化失敗: {e}")
        import traceback
        print("📋 完整錯誤堆疊:")
        traceback.print_exc()
        return False

def init_db_if_needed():
    """延遲初始化資料庫，避免啟動阻塞"""
    global _db_initialized
    
    if _db_initialized:
        return True
    
    try:
        from database import init_database
        config = get_database_config()
        print(f"🗃️ 正在初始化 {config['type']} 資料庫結構...")
        init_database()
        print(f"✅ {config['type']} 資料庫結構初始化完成")
        _db_initialized = True
        return True
    except Exception as e:
        print(f"❌ 資料庫初始化失敗: {e}")
        import traceback
        traceback.print_exc()
        # 不要設置 _db_initialized = True，允許重試
        return False

# 註冊模板全域函數
@app.context_processor
def inject_auth_functions():
    return {
        'has_full_access': has_full_access,
        'get_current_user': get_current_user
    }
RG_API_URL = os.getenv('RG_API_URL')  # 例如: https://api.recommend.games
RG_API_KEY = os.getenv('RG_API_KEY')
# 固定的 RG 預設路徑（不再由用戶設定）
RG_DEFAULT_GAMES_FILE = 'data/bgg_GameItem.jl'
RG_DEFAULT_RATINGS_FILE = 'data/bgg_RatingItem.jl'
RG_DEFAULT_MODEL_DIR = 'data/rg_model'

# RG 抓取任務狀態
rg_task_status = {
    'is_running': False,
    'start_time': None,
    'progress': 0,
    'message': '',
    'last_update': None,
    'stdout_tail': [],
    'stderr_tail': [],
}

def update_rg_task_status(progress=None, message=None, stdout_line=None, stderr_line=None):
    if progress is not None:
        rg_task_status['progress'] = progress
    if message is not None:
        rg_task_status['message'] = message
    if stdout_line:
        rg_task_status['stdout_tail'] = (rg_task_status.get('stdout_tail', []) + [stdout_line])[-50:]
    if stderr_line:
        rg_task_status['stderr_tail'] = (rg_task_status.get('stderr_tail', []) + [stderr_line])[-50:]
    rg_task_status['last_update'] = datetime.now()

def run_rg_scrape_async(games_file: str, ratings_file: str, custom_cmd: str | None = None):
    try:
        rg_task_status['is_running'] = True
        rg_task_status['start_time'] = datetime.now()
        update_rg_task_status(5, '初始化 BGG 資料抓取任務...')

        # 獲取 BGG 用戶名
        bgg_username = get_app_setting('bgg_username')
        if not bgg_username:
            update_rg_task_status(0, 'BGG 用戶名未設定')
            rg_task_status['is_running'] = False
            return

        update_rg_task_status(10, f"開始抓取 BGG 用戶 {bgg_username} 的收藏資料...")

        try:
            # 使用我們的 BGG scraper
            from bgg_scraper_extractor import BGGScraperExtractor
            extractor = BGGScraperExtractor()
            
            update_rg_task_status(20, '正在抓取用戶收藏...')
            
            # 從檔案路徑推導輸出目錄
            output_dir = 'data'
            if games_file:
                output_dir = os.path.dirname(games_file)
            
            # 執行抓取
            success = extractor.export_to_jsonl(bgg_username, output_dir)
            
            if success:
                update_rg_task_status(100, f'成功抓取用戶 {bgg_username} 的 BGG 資料')
            else:
                update_rg_task_status(0, f'抓取用戶 {bgg_username} 的 BGG 資料失敗')
                
        except Exception as e:
            error_msg = f"BGG 抓取過程發生錯誤: {str(e)}"
            update_rg_task_status(0, error_msg)
            logger.error(error_msg)
            import traceback
            logger.error(f"詳細錯誤: {traceback.format_exc()}")
            
    except Exception as e:
        update_rg_task_status(0, f'抓取異常：{e}')
    finally:
        rg_task_status['is_running'] = False

# DB_PATH = "data/bgg_rag.db"  # 移除，改用統一的資料庫連接

def get_report_by_date(report_date, lang='zh-tw'):
    """獲取指定日期的報表內容（優先從資料庫讀取）"""
    try:
        # 優先從資料庫讀取
        with get_db_connection() as conn:
            cursor = conn.cursor()
            config = get_database_config()

            if config['type'] == 'postgresql':
                cursor.execute("""
                    SELECT content, file_size, updated_at
                    FROM reports
                    WHERE report_date = %s AND lang = %s
                """, (report_date, lang))
            else:
                cursor.execute("""
                    SELECT content, file_size, updated_at
                    FROM reports
                    WHERE report_date = ? AND lang = ?
                """, (report_date, lang))

            result = cursor.fetchone()
            if result:
                content, file_size, updated_at = result
                logger.info(f"✅ 從資料庫讀取報表: {report_date}-{lang} ({file_size} bytes)")
                return content, f"report-{report_date}-{lang}.md"

        # 資料庫中沒有，嘗試從檔案讀取
        logger.info(f"⚠️ 資料庫中沒有 {report_date}-{lang} 報表，嘗試從檔案讀取...")
        report_dir = "frontend/public/outputs"
        if not os.path.exists(report_dir):
            return None, "報表目錄不存在"

        # 尋找指定日期的報表
        report_filename = f"report-{report_date}-{lang}.md"
        report_path = os.path.join(report_dir, report_filename)

        if not os.path.exists(report_path):
            return None, f"找不到 {report_date} 的報表"

        with open(report_path, 'r', encoding='utf-8') as f:
            content = f.read()

        logger.info(f"✅ 從檔案讀取報表: {report_path}")
        return content, report_filename

    except Exception as e:
        logger.error(f"讀取報表失敗: {e}")
        return None, f"讀取報表失敗: {e}"

def get_app_setting(key, default=None):
    """讀取應用設定"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            config = get_database_config()
            if config['type'] == 'postgresql':
                cursor.execute("SELECT value FROM app_settings WHERE key = %s", (key,))
            else:
                cursor.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row and row[0] is not None:
                return row[0]
    except Exception as e:
        logger.warning(f"讀取設定失敗: {e}")
    return default

def ensure_app_settings_table():
    """確保 app_settings 表存在"""
    try:
        config = get_database_config()
        logger.info(f"🔧 檢查 app_settings 表，資料庫類型: {config['type']}")
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 檢查表是否已存在 (PostgreSQL)
            cursor.execute("SELECT to_regclass('app_settings')")
            table_exists = cursor.fetchone()[0] is not None
            
            if table_exists:
                logger.info("✅ app_settings 表已存在")
                return True
            
            # 根據資料庫類型創建表
            if config['type'] == 'postgresql':
                create_sql = """
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT NOW()
                )
                """
            else:
                create_sql = """
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            
            logger.info(f"📝 創建 app_settings 表...")
            cursor.execute(create_sql)
            conn.commit()
            logger.info("✅ app_settings 表創建成功")
            return True
    except Exception as e:
        logger.error(f"❌ 創建 app_settings 表失敗: {e}")
        import traceback
        logger.error(f"詳細錯誤: {traceback.format_exc()}")
        return False

def set_app_setting(key, value):
    """寫入應用設定（存在則更新）"""
    try:
        # 確保表存在
        if not ensure_app_settings_table():
            logger.error("無法創建 app_settings 表")
            return False
            
        with get_db_connection() as conn:
            cursor = conn.cursor()
            config = get_database_config()
            # 先嘗試更新
            if config['type'] == 'postgresql':
                cursor.execute("UPDATE app_settings SET value = %s, updated_at = NOW() WHERE key = %s", (value, key))
            else:
                cursor.execute("UPDATE app_settings SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?", (value, key))
            if cursor.rowcount == 0:
                # 插入
                if config['type'] == 'postgresql':
                    cursor.execute("INSERT INTO app_settings (key, value, updated_at) VALUES (%s, %s, NOW())", (key, value))
                else:
                    cursor.execute("INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)", (key, value))
            conn.commit()
            logger.info(f"✅ 設定已保存: {key} = {value}")
            return True
    except Exception as e:
        logger.error(f"寫入設定失敗: {e}")
        return False

def fetch_bgg_collection_xml(username, params, max_retries=10, initial_delay=2):
    """呼叫 BGG Collection API，處理 202 重試機制"""
    base_url = "https://boardgamegeek.com/xmlapi2/collection"
    query = {"username": username, **params}
    delay = initial_delay
    for attempt in range(1, max_retries + 1):
        resp = requests.get(base_url, params=query, timeout=30)
        if resp.status_code == 200:
            return resp.text
        if resp.status_code == 202:
            logger.info(f"BGG 回應 202（排隊中），第 {attempt}/{max_retries} 次重試，等待 {delay}s...")
            time.sleep(delay)
            delay = min(delay * 1.5, 30)
            continue
        raise RuntimeError(f"BGG API 失敗，狀態碼: {resp.status_code}")
    raise TimeoutError("BGG API 多次重試仍為 202，請稍後再試")

def parse_bgg_collection(xml_text):
    """解析 BGG Collection XML -> list[dict]"""
    soup = BeautifulSoup(xml_text, "xml")
    items = []
    for item in soup.find_all("item"):
        try:
            objectid = int(item.get("objectid"))
        except Exception:
            continue
        name_tag = item.find("name")
        name = name_tag.text if name_tag else str(objectid)
        status_tag = item.find("status")
        status_attrs = status_tag.attrs if status_tag else {}
        stats_tag = item.find("stats")
        rating_value = None
        wishlist_priority = None
        if stats_tag:
            rating_tag = stats_tag.find("rating")
            if rating_tag and rating_tag.get("value") and rating_tag.get("value") != "N/A":
                try:
                    rating_value = float(rating_tag.get("value"))
                except Exception:
                    rating_value = None
        if status_attrs.get("wishlist") in ("1", 1, True):
            try:
                wishlist_priority = int(status_attrs.get("wishlistpriority", 0))
            except Exception:
                wishlist_priority = None
        items.append({
            "objectid": objectid,
            "name": name,
            "status_json": json.dumps(status_attrs, ensure_ascii=False),
            "rating": rating_value,
            "wish_priority": wishlist_priority
        })
    return items

def upsert_collection_items(items):
    """將收藏清單寫入資料庫（更新或插入）"""
    if not items:
        return 0
    count = 0
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            config = get_database_config()
            for it in items:
                # update first
                if config['type'] == 'postgresql':
                    cursor.execute(
                        """
                        UPDATE collection
                        SET name = %s, status = %s, rating = %s, wish_priority = %s, last_sync = NOW()
                        WHERE objectid = %s
                        """,
                        (it["name"], it["status_json"], it["rating"], it["wish_priority"], it["objectid"])
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE collection
                        SET name = ?, status = ?, rating = ?, wish_priority = ?, last_sync = CURRENT_TIMESTAMP
                        WHERE objectid = ?
                        """,
                        (it["name"], it["status_json"], it["rating"], it["wish_priority"], it["objectid"])
                    )
                if cursor.rowcount == 0:
                    # insert
                    if config['type'] == 'postgresql':
                        cursor.execute(
                            """
                            INSERT INTO collection (objectid, name, status, rating, wish_priority, last_sync)
                            VALUES (%s, %s, %s, %s, %s, NOW())
                            """,
                            (it["objectid"], it["name"], it["status_json"], it["rating"], it["wish_priority"])
                        )
                    else:
                        cursor.execute(
                            """
                            INSERT INTO collection (objectid, name, status, rating, wish_priority, last_sync)
                            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                            """,
                            (it["objectid"], it["name"], it["status_json"], it["rating"], it["wish_priority"])
                        )
                count += 1
            conn.commit()
    except Exception as e:
        logger.error(f"寫入收藏清單失敗: {e}")
    return count

def build_recommendations_from_collection(limit=20):
    """根據使用者收藏與資料庫遊戲特徵產生推薦（簡易相似度）"""
    # 取出使用者收藏的 objectid 清單
    collected_ids = []
    with get_db_connection() as conn:
        cursor = conn.cursor()
        config = get_database_config()
        try:
            cursor.execute("SELECT objectid FROM collection")
            collected_ids = [row[0] for row in cursor.fetchall()]
        except Exception:
            collected_ids = []

    if not collected_ids:
        return []

    # 取出收藏遊戲的特徵集合
    favorite_categories = set()
    favorite_mechanics = set()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        config = get_database_config()
        placeholders = ','.join(['%s' if config['type'] == 'postgresql' else '?'] * len(collected_ids))
        try:
            cursor.execute(
                f"SELECT categories, mechanics FROM game_detail WHERE objectid IN ({placeholders})",
                collected_ids
            )
            for cat_str, mech_str in cursor.fetchall():
                if cat_str:
                    favorite_categories.update([c.strip() for c in cat_str.split(',') if c.strip()])
                if mech_str:
                    favorite_mechanics.update([m.strip() for m in mech_str.split(',') if m.strip()])
        except Exception as e:
            logger.warning(f"讀取收藏特徵失敗: {e}")

    # 掃描候選遊戲（排除已收藏）
    candidates = []
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT objectid, name, rating, rank, weight, minplayers, maxplayers, minplaytime, maxplaytime, image, categories, mechanics FROM game_detail")
            for row in cursor.fetchall():
                oid, name, rating, bgg_rank, weight, minp, maxp, minpt, maxpt, image, cat_str, mech_str = row
                if oid in collected_ids:
                    continue
                cats = set([c.strip() for c in (cat_str or '').split(',') if c.strip()])
                mechs = set([m.strip() for m in (mech_str or '').split(',') if m.strip()])
                # Jaccard 相似度（類別與機制）
                cat_sim = len(cats & favorite_categories) / len(cats | favorite_categories) if (cats or favorite_categories) else 0
                mech_sim = len(mechs & favorite_mechanics) / len(mechs | favorite_mechanics) if (mechs or favorite_mechanics) else 0
                sim = 0.6 * mech_sim + 0.4 * cat_sim
                # 加權評分（偏好高評分與高排名）
                score = sim
                if rating:
                    score += 0.1 * (rating - 6.5)  # 平移
                if bgg_rank and bgg_rank > 0:
                    score += 0.05 * (2000 / (bgg_rank + 200))
                candidates.append({
                    'objectid': oid, 'name': name, 'image': image, 'rating': rating, 'bgg_rank': bgg_rank,
                    'weight': weight, 'min_players': minp, 'max_players': maxp, 'minplaytime': minpt, 'maxplaytime': maxpt,
                    'similarity': sim, 'score': score
                })
        except Exception as e:
            logger.error(f"讀取候選遊戲失敗: {e}")
            return []

    candidates.sort(key=lambda x: x['score'], reverse=True)
    topk = candidates[:limit]
    return topk

def get_advanced_recommendations(username, owned_ids, algorithm='hybrid', limit=10):
    """使用進階推薦算法"""
    try:
        logger.info(f"🔍 開始進階推薦 - 用戶: {username}, 擁有遊戲: {len(owned_ids) if owned_ids else 0}, 算法: {algorithm}")
        
        from advanced_recommender import AdvancedBoardGameRecommender
        
        recommender = AdvancedBoardGameRecommender()
        
        # 檢查資料庫狀態
        logger.info("🔧 檢查資料庫狀態...")
        if not recommender.check_database_connection():
            logger.error("❌ 資料庫檔案不存在，請先執行資料收集")
            return None
            
        if not recommender.check_tables_exist():
            logger.error("❌ 資料庫中缺少必要的資料表，請先執行資料收集")
            return None
        
        logger.info("📊 載入推薦資料...")
        if not recommender.load_data():
            logger.error("❌ 無法載入資料庫資料")
            return None
        
        # 檢查是否有足夠的資料
        logger.info(f"📈 資料統計 - 遊戲: {len(recommender.games_df)}, 評分: {len(recommender.ratings_df)}")
        if len(recommender.games_df) == 0:
            logger.error("❌ 沒有遊戲資料可用於推薦")
            return None
        
        logger.info("🧠 準備推薦模型...")
        recommender.prepare_user_item_matrix()
        recommender.prepare_content_features()
        recommender.train_all_models()
        
        logger.info(f"🎯 執行 {algorithm} 推薦算法...")
        if algorithm == 'popularity':
            recommendations = recommender.recommend_popularity(owned_ids, limit)
        elif algorithm == 'content':
            recommendations = recommender.recommend_content_based(owned_ids, limit)
        elif algorithm == 'hybrid':
            recommendations = recommender.recommend_hybrid(owned_ids, limit)
        else:
            recommendations = recommender.recommend_hybrid(owned_ids, limit)
        
        logger.info(f"📋 推薦算法返回了 {len(recommendations) if recommendations else 0} 個結果")
        
        # 檢查是否有推薦結果
        if not recommendations:
            logger.warning(f"⚠️ 進階推薦器 ({algorithm}) 沒有產生任何推薦結果")
            logger.info("🔍 調試信息：")
            logger.info(f"  - 擁有遊戲數量: {len(owned_ids) if owned_ids else 0}")
            logger.info(f"  - 資料庫遊戲數量: {len(recommender.games_df)}")
            logger.info(f"  - 用戶-物品矩陣大小: {recommender.user_item_matrix.shape if recommender.user_item_matrix is not None else 'None'}")
            return None
        
        # 轉換格式以符合現有介面
        logger.info("🔄 轉換推薦結果格式...")
        formatted_recs = []
        for i, rec in enumerate(recommendations):
            try:
                formatted_rec = {
                    'game_id': rec['game_id'],
                    'name': rec['name'],
                    'year': rec['year'],
                    'rating': rec['rating'],
                    'rank': rec.get('rank', 0),
                    'weight': rec.get('weight', 0),
                    'min_players': rec.get('min_players', 1),
                    'max_players': rec.get('max_players', 1),
                    'rec_score': rec['rec_score'],
                    'source': f'advanced_{algorithm}'
                }
                formatted_recs.append(formatted_rec)
                if i < 3:  # 只記錄前3個推薦的詳細信息
                    logger.info(f"  推薦 {i+1}: {rec['name']} (分數: {rec['rec_score']})")
            except Exception as format_error:
                logger.error(f"格式化推薦結果時發生錯誤: {format_error}, 推薦內容: {rec}")
                continue
        
        logger.info(f"✅ 進階推薦器 ({algorithm}) 成功產生了 {len(formatted_recs)} 個推薦")
        return formatted_recs
        
    except Exception as e:
        logger.error(f"❌ 進階推薦器發生錯誤: {e}")
        import traceback
        logger.error(f"詳細錯誤堆疊: {traceback.format_exc()}")
        return None

def get_local_recommendations(username, owned_ids, limit=10):
    """使用本地資料庫和 BGG API 提供基於熱門度的推薦"""
    try:
        owned_set = set(owned_ids) if owned_ids else set()
        
        # 步驟 1: 從本地資料庫獲取基礎推薦
        local_recommendations = []
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 構建排除已擁有遊戲的 WHERE 條件
            config = get_database_config()
            if owned_set:
                if config['type'] == 'postgresql':
                    placeholders = ','.join(['%s'] * len(owned_set))
                else:
                    placeholders = ','.join(['?'] * len(owned_set))
                exclude_clause = f"AND g.objectid NOT IN ({placeholders})"
                params = list(owned_set) + [min(limit, 50)]  # 最多取50個本地推薦
            else:
                exclude_clause = ""
                params = [min(limit, 50)]
            
            # 查詢推薦遊戲（基於評分和排名）
            limit_placeholder = '%s' if config['type'] == 'postgresql' else '?'
            query = f"""
            SELECT 
                g.objectid,
                g.name,
                g.year,
                g.rating,
                g.rank,
                g.weight,
                g.minplayers,
                g.maxplayers,
                COALESCE(g.rating, 0) + 
                CASE 
                    WHEN g.rank > 0 THEN (10000 - g.rank) / 1000.0 
                    ELSE 0 
                END as popularity_score
            FROM game_detail g
            WHERE g.objectid IS NOT NULL 
                AND g.name IS NOT NULL
                {exclude_clause}
            ORDER BY popularity_score DESC, g.rating DESC
            LIMIT {limit_placeholder}
            """
            
            cursor.execute(query, params)
            games = cursor.fetchall()
            
            for game in games:
                local_recommendations.append({
                    'game_id': game[0],
                    'name': game[1],
                    'year': game[2] or '',
                    'rating': round(game[3] or 0, 1),
                    'rank': game[4] or 0,
                    'weight': round(game[5] or 0, 1),
                    'min_players': game[6] or 1,
                    'max_players': game[7] or 1,
                    'rec_score': round(game[8], 2),
                    'source': 'local_db'
                })
        
        # 步驟 2: 如果本地推薦不足，使用 BGG 熱門遊戲補充
        if len(local_recommendations) < limit:
            logger.info(f"本地推薦只有 {len(local_recommendations)} 個，嘗試從 BGG 獲取更多推薦")
            
            # BGG 熱門遊戲 ID（這些是一些知名的熱門遊戲）
            popular_game_ids = [
                174430,  # Gloomhaven
                161936,  # Pandemic Legacy: Season 1
                169786,  # Scythe
                120677,  # Terra Mystica
                167791,  # Terraforming Mars
                224517,  # Brass: Birmingham
                193738,  # Great Western Trail
                182028,  # Through the Ages: A New Story of Civilization
                233078,  # Twilight Imperium: Fourth Edition
                205637,  # Arkham Horror: The Card Game
                266192,  # Wingspan
                31260,   # Agricola
                36218,   # Dominion
                84876,   # The Castles of Burgundy
                148228,  # Splendor
                30549,   # Pandemic
                103343,  # King of Tokyo
                124742,  # Android: Netrunner
                254640,  # Azul
                13,      # Catan
                68448,   # 7 Wonders
                70323,   # King of New York
                146508,  # Eldritch Horror
                12333,   # Twilight Struggle
                150376,  # Gloom
            ]
            
            # 排除已擁有的遊戲
            available_ids = [gid for gid in popular_game_ids if gid not in owned_set]
            local_game_ids = {rec['game_id'] for rec in local_recommendations}
            new_ids = [gid for gid in available_ids if gid not in local_game_ids]
            
            # 只取需要的數量
            needed = limit - len(local_recommendations)
            bgg_ids = new_ids[:needed]
            
            if bgg_ids:
                # 從 BGG API 獲取詳細資料
                bgg_details = fetch_game_details_from_bgg(bgg_ids)
                
                for game_id, details in bgg_details.items():
                    local_recommendations.append({
                        'game_id': details['id'],
                        'name': details['name'],
                        'year': details['year'],
                        'rating': details['rating'],
                        'rank': details['rank'],
                        'weight': details['weight'],
                        'min_players': details['min_players'],
                        'max_players': details['max_players'],
                        'rec_score': details['rating'],  # 使用 BGG 評分作為推薦分數
                        'source': 'bgg_popular'
                    })
        
        # 按推薦分數排序並限制數量
        local_recommendations.sort(key=lambda x: x['rec_score'], reverse=True)
        final_recommendations = local_recommendations[:limit]
        
        logger.info(f"總共產生了 {len(final_recommendations)} 個推薦 (本地: {len([r for r in final_recommendations if r['source'] == 'local_db'])}, BGG: {len([r for r in final_recommendations if r['source'] == 'bgg_popular'])})")
        return final_recommendations
        
    except Exception as e:
        logger.error(f"本地推薦器發生錯誤: {e}")
        return None

def fetch_game_details_from_bgg(game_ids):
    """從 BGG API 獲取遊戲詳細資訊"""
    if not game_ids:
        return {}
    
    try:
        import xml.etree.ElementTree as ET
        import time
        
        # BGG API 限制一次最多查詢20個遊戲
        game_details = {}
        
        for i in range(0, len(game_ids), 20):
            batch_ids = game_ids[i:i+20]
            ids_str = ','.join(map(str, batch_ids))
            
            # 構建 BGG API URL
            url = f'https://boardgamegeek.com/xmlapi2/thing?id={ids_str}&type=boardgame&stats=1'
            
            try:
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                
                # 解析 XML 響應
                root = ET.fromstring(response.content)
                
                for item in root.findall('item'):
                    game_id = int(item.get('id'))
                    
                    # 提取基本資訊
                    name_elem = item.find('.//name[@type="primary"]')
                    name = name_elem.get('value') if name_elem is not None else f'遊戲 {game_id}'
                    
                    year_elem = item.find('yearpublished')
                    year = int(year_elem.get('value')) if year_elem is not None and year_elem.get('value') else 0
                    
                    # 提取統計資訊
                    stats = item.find('statistics/ratings')
                    rating = 0.0
                    rank = 0
                    weight = 0.0
                    
                    if stats is not None:
                        average_elem = stats.find('average')
                        if average_elem is not None:
                            rating = float(average_elem.get('value') or 0)
                        
                        # 尋找 BoardGame Rank
                        for rank_elem in stats.findall('.//rank'):
                            if rank_elem.get('name') == 'boardgame':
                                rank_value = rank_elem.get('value')
                                if rank_value and rank_value != 'Not Ranked':
                                    rank = int(rank_value)
                                break
                        
                        weight_elem = stats.find('averageweight')
                        if weight_elem is not None:
                            weight = float(weight_elem.get('value') or 0)
                    
                    # 提取玩家數量
                    minplayers_elem = item.find('minplayers')
                    maxplayers_elem = item.find('maxplayers')
                    min_players = int(minplayers_elem.get('value')) if minplayers_elem is not None else 1
                    max_players = int(maxplayers_elem.get('value')) if maxplayers_elem is not None else 1
                    
                    # 提取遊戲時間
                    playingtime_elem = item.find('playingtime')
                    playing_time = int(playingtime_elem.get('value')) if playingtime_elem is not None else 0
                    
                    game_details[game_id] = {
                        'id': game_id,
                        'name': name,
                        'year': year,
                        'rating': round(rating, 1),
                        'rank': rank,
                        'weight': round(weight, 1),
                        'min_players': min_players,
                        'max_players': max_players,
                        'playing_time': playing_time,
                        'source': 'bgg_api'
                    }
                
                # BGG API 要求限制請求頻率
                if i + 20 < len(game_ids):
                    time.sleep(1)
                    
            except Exception as e:
                logger.error(f"獲取遊戲 {batch_ids} 的 BGG 資料時發生錯誤: {e}")
                continue
        
        logger.info(f"從 BGG API 獲取了 {len(game_details)} 個遊戲的詳細資料")
        return game_details
        
    except Exception as e:
        logger.error(f"BGG API 查詢發生錯誤: {e}")
        return {}

def call_recommend_games_api(bgg_username: str, owned_ids: list[int], limit: int = 30):
    """可選：呼叫 Recommend.Games 的外部 API（若有設定環境變數）。
    注意：此為預留，實際端點與參數需依官方文件調整。
    """
    if not RG_API_URL:
        return None, '未設定 RG_API_URL，改為顯示前往外部網站的連結'
    try:
        headers = {'Authorization': f'Bearer {RG_API_KEY}'} if RG_API_KEY else {}
        payload = {
            'username': bgg_username,
            'owned_ids': owned_ids,
            'limit': limit
        }
        resp = requests.post(f"{RG_API_URL}/recommend", json=payload, headers=headers, timeout=30)
        if resp.status_code != 200:
            return None, f"外部服務回應 {resp.status_code}"
        return resp.json(), None
    except Exception as e:
        logger.warning(f"呼叫 Recommend.Games 外部服務失敗: {e}")
        return None, str(e)

def get_latest_report():
    """獲取最新的報表內容（優先從資料庫讀取）"""
    try:
        # 優先從資料庫讀取最新報表
        with get_db_connection() as conn:
            cursor = conn.cursor()
            config = get_database_config()

            if config['type'] == 'postgresql':
                cursor.execute("""
                    SELECT report_date, lang, content, file_size, updated_at
                    FROM reports
                    WHERE lang = 'zh-tw'
                    ORDER BY report_date DESC, updated_at DESC
                    LIMIT 1
                """)
            else:
                cursor.execute("""
                    SELECT report_date, lang, content, file_size, updated_at
                    FROM reports
                    WHERE lang = 'zh-tw'
                    ORDER BY report_date DESC, updated_at DESC
                    LIMIT 1
                """)

            result = cursor.fetchone()
            if result:
                report_date, lang, content, file_size, updated_at = result
                logger.info(f"✅ 從資料庫讀取最新報表: {report_date}-{lang} ({file_size} bytes)")
                return content, f"report-{report_date}-{lang}.md"

        # 資料庫中沒有，嘗試從檔案讀取
        logger.info("⚠️ 資料庫中沒有報表，嘗試從檔案讀取...")
        # 尋找最新的報表檔案
        report_dir = "frontend/public/outputs"
        if not os.path.exists(report_dir):
            return None, "報表目錄不存在"

        # 尋找最新的繁體中文報表
        report_files = [f for f in os.listdir(report_dir) if f.endswith('-zh-tw.md')]
        if not report_files:
            return None, "找不到報表檔案"

        # 取得最新的報表
        latest_file = sorted(report_files)[-1]
        report_path = os.path.join(report_dir, latest_file)

        with open(report_path, 'r', encoding='utf-8') as f:
            content = f.read()

        logger.info(f"✅ 從檔案讀取最新報表: {report_path}")
        return content, latest_file

    except Exception as e:
        logger.error(f"讀取報表失敗: {e}")
        return None, "讀取報表失敗"

def get_available_dates():
    """獲取所有可用的報表日期（優先從資料庫讀取）"""
    try:
        dates_set = set()

        # 優先從資料庫讀取
        with get_db_connection() as conn:
            cursor = conn.cursor()
            config = get_database_config()

            if config['type'] == 'postgresql':
                cursor.execute("""
                    SELECT DISTINCT report_date
                    FROM reports
                    WHERE lang = 'zh-tw'
                    ORDER BY report_date DESC
                """)
            else:
                cursor.execute("""
                    SELECT DISTINCT report_date
                    FROM reports
                    WHERE lang = 'zh-tw'
                    ORDER BY report_date DESC
                """)

            db_dates = [row[0] for row in cursor.fetchall()]
            dates_set.update(db_dates)

            if db_dates:
                logger.info(f"✅ 從資料庫讀取到 {len(db_dates)} 個報表日期")

        # 同時從檔案系統讀取（作為備份）
        report_dir = "frontend/public/outputs"
        if os.path.exists(report_dir):
            report_files = [f for f in os.listdir(report_dir) if f.endswith('-zh-tw.md')]
            file_dates = [f.replace('report-', '').replace('-zh-tw.md', '') for f in report_files]
            dates_set.update(file_dates)

            if file_dates:
                logger.info(f"✅ 從檔案系統讀取到 {len(file_dates)} 個報表日期")

        # 合併並排序
        all_dates = sorted(list(dates_set), reverse=True)
        logger.info(f"📊 總共可用報表日期: {len(all_dates)} 個")
        return all_dates

    except Exception as e:
        logger.error(f"獲取可用日期失敗: {e}")
        return []

def get_game_details_from_db(objectid):
    """從資料庫獲取遊戲的完整詳細資料"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            config = get_database_config()

            # 獲取遊戲基本資料（包含字串格式的分類機制資料）
            if config['type'] == 'postgresql':
                cursor.execute("""
                    SELECT rating, rank, weight, minplayers, maxplayers, bestplayers,
                           minplaytime, maxplaytime, image, categories, mechanics,
                           designers, artists, publishers
                    FROM game_detail
                    WHERE objectid = %s
                """, (objectid,))
            else:
                cursor.execute("""
                    SELECT rating, rank, weight, minplayers, maxplayers, bestplayers,
                           minplaytime, maxplaytime, image, categories, mechanics,
                           designers, artists, publishers
                    FROM game_detail
                    WHERE objectid = ?
                """, (objectid,))

            game_detail = cursor.fetchone()

            # 獲取所有類型的分類資料
            if config['type'] == 'postgresql':
                cursor.execute("""
                    SELECT bi.id, bi.name, bi.category
                    FROM bgg_items bi
                    JOIN game_categories gc ON bi.id = gc.category_id AND bi.category = gc.category_type
                    WHERE gc.objectid = %s
                    ORDER BY bi.category, bi.name
                """, (objectid,))
            else:
                cursor.execute("""
                    SELECT bi.id, bi.name, bi.category
                    FROM bgg_items bi
                    JOIN game_categories gc ON bi.id = gc.category_id AND bi.category = gc.category_type
                    WHERE gc.objectid = ?
                    ORDER BY bi.category, bi.name
                """, (objectid,))

            category_results = cursor.fetchall()

        # 組織分類資料
        categories = {'boardgamecategory': [], 'boardgamemechanic': [],
                     'boardgamedesigner': [], 'boardgameartist': [], 'boardgamepublisher': []}

        for cat_id, name, category in category_results:
            if category in categories:
                categories[category].append({'id': cat_id, 'name': name})

        # 處理字串格式的分類資料（作為備用）
        def parse_string_to_dict_list(text):
            """將逗號分隔的字串轉換為字典列表格式"""
            if not text or not text.strip():
                return []
            items = [item.strip() for item in text.split(',') if item.strip()]
            return [{'id': None, 'name': item} for item in items]

        # 組織返回資料
        if game_detail:
            # 如果從 bgg_items 表中沒有取得分類資料，使用字串資料
            final_categories = categories['boardgamecategory']
            final_mechanics = categories['boardgamemechanic']
            final_designers = categories['boardgamedesigner']
            final_artists = categories['boardgameartist']
            final_publishers = categories['boardgamepublisher']

            # 如果沒有結構化資料，解析字串
            if not final_categories and len(game_detail) > 9:
                final_categories = parse_string_to_dict_list(game_detail[9])
            if not final_mechanics and len(game_detail) > 10:
                final_mechanics = parse_string_to_dict_list(game_detail[10])
            if not final_designers and len(game_detail) > 11:
                final_designers = parse_string_to_dict_list(game_detail[11])
            if not final_artists and len(game_detail) > 12:
                final_artists = parse_string_to_dict_list(game_detail[12])
            if not final_publishers and len(game_detail) > 13:
                final_publishers = parse_string_to_dict_list(game_detail[13])

            return {
                'rating': game_detail[0],
                'bgg_rank': game_detail[1],  # BGG總排名
                'weight': game_detail[2],
                'min_players': game_detail[3],
                'max_players': game_detail[4],
                'bestplayers': game_detail[5],
                'minplaytime': game_detail[6],
                'maxplaytime': game_detail[7],
                'image': game_detail[8],
                'categories': final_categories,
                'mechanics': final_mechanics,
                'designers': final_designers,
                'artists': final_artists,
                'publishers': final_publishers
            }
        else:
            return {
                'rating': None,
                'bgg_rank': None,
                'weight': None,
                'min_players': None,
                'max_players': None,
                'bestplayers': None,
                'minplaytime': None,
                'maxplaytime': None,
                'image': None,
                'categories': categories['boardgamecategory'],
                'mechanics': categories['boardgamemechanic'],
                'designers': categories['boardgamedesigner'],
                'artists': categories['boardgameartist'],
                'publishers': categories['boardgamepublisher']
            }

    except Exception as e:
        logger.error(f"獲取遊戲詳細資料失敗: {e}")
        return {
            'rating': None,
            'bgg_rank': None,
            'weight': None,
            'min_players': None,
            'max_players': None,
            'bestplayers': None,
            'minplaytime': None,
            'maxplaytime': None,
            'image': None,
            'categories': [],
            'mechanics': [],
            'designers': [],
            'artists': [],
            'publishers': []
        }

def get_game_categories_from_db(objectid):
    """從資料庫獲取遊戲的分類資訊（包含ID）- 保持向後兼容"""
    details = get_game_details_from_db(objectid)
    return {
        'boardgamecategory': details['categories'],
        'boardgamemechanic': details['mechanics'],
        'boardgamedesigner': details['designers'],
        'boardgameartist': details['artists'],
        'boardgamepublisher': details['publishers']
    }

def parse_game_data_from_report(content):
    """從報表內容解析遊戲資料"""
    games = []
    if not content:
        return games

    try:
        # 解析排行榜表格
        lines = content.split('\n')
        in_table = False

        for line in lines:
            line = line.strip()

            # 檢查是否是表格開始
            if '| 排名 | 桌遊 | 年份 | 排名變化 |' in line:
                in_table = True
                continue
            elif '|------|------|------|----------|' in line:
                continue
            elif in_table and line.startswith('|') and '|' in line:
                # 解析表格行
                parts = [p.strip() for p in line.split('|') if p.strip()]
                if len(parts) >= 4:
                    try:
                        rank = int(parts[0])
                        # 移除限制，獲取所有遊戲資料

                        # 提取遊戲名稱和連結
                        game_cell = parts[1]
                        name_match = re.search(r'\[([^\]]+)\]', game_cell)
                        game_name = name_match.group(1) if name_match else '未知遊戲'

                        # 提取遊戲ID（從BGG連結中）
                        bgg_link_match = re.search(r'https://boardgamegeek\.com/boardgame/(\d+)', game_cell)
                        game_objectid = int(bgg_link_match.group(1)) if bgg_link_match else None

                        # 提取圖片URL
                        img_match = re.search(r'<img src="([^"]+)"', game_cell)
                        image_url = img_match.group(1) if img_match else None

                        # 提取年份
                        year = parts[2]

                        # 解析排名變化
                        rank_change_cell = parts[3]
                        rank_change = 0
                        is_new = False

                        if '⬆️' in rank_change_cell:
                            change_match = re.search(r'⬆️\s*(\d+)', rank_change_cell)
                            if change_match:
                                rank_change = int(change_match.group(1))
                        elif '⬇️' in rank_change_cell:
                            change_match = re.search(r'⬇️\s*(\d+)', rank_change_cell)
                            if change_match:
                                rank_change = -int(change_match.group(1))
                        elif '🆕' in rank_change_cell:
                            is_new = True

                        # 暫時存儲遊戲ID，稍後批量查詢
                        db_details = {}

                        games.append({
                            'rank': rank,
                            'name': game_name,
                            'objectid': game_objectid,
                            'year': year,
                            'image': db_details.get('image') or image_url,
                            'rank_change': rank_change,
                            'is_new': is_new,
                            'rating': db_details.get('rating') or '8.0',
                            'bgg_rank': db_details.get('bgg_rank'),
                            'weight': db_details.get('weight'),
                            'min_players': db_details.get('min_players') or 1,
                            'max_players': db_details.get('max_players') or 4,
                            'bestplayers': db_details.get('bestplayers'),
                            'playtime': 60,  # 預設值，後續會更新
                            'minplaytime': db_details.get('minplaytime'),
                            'maxplaytime': db_details.get('maxplaytime'),
                            'categories': db_details.get('categories', []),
                            'mechanics': db_details.get('mechanics', []),
                            'designers': db_details.get('designers', []),
                            'artists': db_details.get('artists', []),
                            'publishers': db_details.get('publishers', []),
                            'reason': None
                        })

                    except (ValueError, IndexError) as e:
                        logger.warning(f"解析排行榜行失敗: {line}, 錯誤: {e}")
                        continue
            elif in_table and not line.startswith('|'):
                # 表格結束
                break

        # 批量取得所有遊戲的資料庫詳細資訊
        logger.info(f"批量查詢 {len(games)} 個遊戲的詳細資料...")

        # 批量查詢 reason 資料
        reason_objectids = [game['objectid'] for game in games if game['objectid']]
        reasons_dict = {}
        if reason_objectids:
            try:
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    config = get_database_config()
                    placeholders = ','.join(['%s'] * len(reason_objectids))
                    query = f"SELECT objectid, reason FROM forum_threads_i18n WHERE objectid IN ({placeholders}) AND lang = 'zh-tw'"
                    cursor.execute(query, reason_objectids)
                    for oid, reason in cursor.fetchall():
                        reasons_dict[oid] = reason
                logger.info(f"✅ 從資料庫載入 {len(reasons_dict)} 個遊戲的 reason 資料")
            except Exception as e:
                logger.warning(f"查詢 reason 資料失敗: {e}")

        for game in games:
            if game['objectid']:
                try:
                    db_details = get_game_details_from_db(game['objectid'])
                    # 更新遊戲資料
                    game.update({
                        'image': db_details.get('image') or game.get('image'),
                        'rating': db_details.get('rating') or game.get('rating', '8.0'),
                        'bgg_rank': db_details.get('bgg_rank'),
                        'weight': db_details.get('weight'),
                        'min_players': db_details.get('min_players') or game.get('min_players', 1),
                        'max_players': db_details.get('max_players') or game.get('max_players', 4),
                        'bestplayers': db_details.get('bestplayers'),
                        'minplaytime': db_details.get('minplaytime'),
                        'maxplaytime': db_details.get('maxplaytime'),
                        'categories': db_details.get('categories', []),
                        'mechanics': db_details.get('mechanics', []),
                        'designers': db_details.get('designers', []),
                        'artists': db_details.get('artists', []),
                        'publishers': db_details.get('publishers', [])
                    })

                    # 從資料庫讀取 reason
                    if game['objectid'] in reasons_dict:
                        game['reason'] = reasons_dict[game['objectid']]
                        logger.info(f"✅ 為 {game['name']} 載入資料庫 reason")

                except Exception as e:
                    logger.warning(f"取得遊戲 {game['objectid']} 的詳細資料失敗: {e}")

        # 解析詳細資料區段來獲取更多資訊
        for game in games:
            game_section_pattern = f"### <a id='{re.escape(game['name'].replace(' ', '-').replace(':', ''))}.*?</a>{re.escape(game['name'])}"
            match = re.search(game_section_pattern, content, re.DOTALL)
            if match:
                section_start = match.end()
                # 找到下一個遊戲區段或結束
                next_game_match = re.search(r'###\s+<a id=', content[section_start:])
                if next_game_match:
                    section_end = section_start + next_game_match.start()
                else:
                    section_end = len(content)

                section_content = content[section_start:section_end]

                # 提取評分
                rating_match = re.search(r'Rating.*?(\d+\.\d+)/10', section_content)
                if rating_match:
                    game['rating'] = rating_match.group(1)

                # 提取人數
                players_match = re.search(r'人數.*?(\d+)～(\d+)\s*人', section_content)
                if players_match:
                    game['min_players'] = int(players_match.group(1))
                    game['max_players'] = int(players_match.group(2))

                # 提取時間
                time_match = re.search(r'時間.*?(\d+)～(\d+)\s*分鐘', section_content)
                if time_match:
                    game['playtime'] = int(time_match.group(2))
                elif re.search(r'時間.*?(\d+)\s*分鐘', section_content):
                    time_single_match = re.search(r'時間.*?(\d+)\s*分鐘', section_content)
                    game['playtime'] = int(time_single_match.group(1))

                # 提取分類
                category_match = re.search(r'分類.*?：\s*([^\n]+)', section_content)
                if category_match:
                    categories = [{'name': cat.strip()} for cat in category_match.group(1).split(',')]
                    game['categories'] = categories

                # 提取機制
                mechanic_match = re.search(r'機制.*?：\s*([^\n]+)', section_content)
                if mechanic_match:
                    mechanics = [{'name': mech.strip()} for mech in mechanic_match.group(1).split(',')]
                    game['mechanics'] = mechanics

                # 提取設計師
                designer_match = re.search(r'設計師.*?：\s*([^\n]+)', section_content)
                if designer_match:
                    designers = [{'name': designer.strip()} for designer in designer_match.group(1).split(',')]
                    game['designers'] = designers

                # 提取美術
                artist_match = re.search(r'美術.*?：\s*([^\n]+)', section_content)
                if artist_match:
                    artists = [{'name': artist.strip()} for artist in artist_match.group(1).split(',')]
                    game['artists'] = artists

                # 提取發行商
                publisher_match = re.search(r'發行商.*?：\s*([^\n]+)', section_content)
                if publisher_match:
                    publishers = [{'name': pub.strip()} for pub in publisher_match.group(1).split(',')]
                    game['publishers'] = publishers

                # 提取上榜原因
                reason_match = re.search(r'\*\*📈 上榜原因推論：\*\*\s*>\s*(.*?)(?=\n---|\n###|\n##|$)', section_content, re.DOTALL)
                if reason_match:
                    reason_text = reason_match.group(1).strip()
                    logger.info(f"✅ 找到 {game['name']} 的原始推論文字: {reason_text[:100]}...")
                    # 清理多餘的空白和換行並移除前綴
                    reason_text = re.sub(r'\s+', ' ', reason_text)
                    # 移除《遊戲名》近期上榜的主要原因是 這類前綴
                    reason_text = re.sub(r'^《[^》]+》[^，。]*?[的是]', '', reason_text)
                    # 移除其他可能的前綴
                    reason_text = re.sub(r'^[^，。]*?主要原因是', '', reason_text)
                    reason_text = reason_text.strip()
                    logger.info(f"✅ {game['name']} 清理後的推論文字: {reason_text[:100]}...")
                    game['reason'] = reason_text
                else:
                    logger.warning(f"⚠️ 未找到 {game['name']} 的上榜原因推論")
                    # 顯示區段內容以便除錯
                    logger.debug(f"📝 {game['name']} 的區段內容前200字元: {section_content[:200]}...")
                    # 檢查是否包含推論關鍵字
                    if '📈 上榜原因推論' in section_content:
                        logger.info(f"🔍 {game['name']} 的區段包含推論關鍵字，但正則表達式無法匹配")
                    elif '因為技術問題' in section_content:
                        logger.info(f"🔍 {game['name']} 顯示技術問題訊息")
                    else:
                        # 為沒有詳細分析區段的遊戲提供預設訊息
                        game['reason'] = "此遊戲未包含在詳細分析範圍內，可能是因為討論熱度較低或為常駐榜單遊戲。"
                        logger.info(f"🔄 為 {game['name']} 設定預設上榜原因說明")
            else:
                # 沒有找到詳細區段的遊戲，提供預設訊息
                game['reason'] = "此遊戲未包含在詳細分析範圍內，可能是因為討論熱度較低或為常駐榜單遊戲。"
                logger.info(f"🔄 為 {game['name']} 設定預設上榜原因說明（未找到詳細區段）")

        return games

    except Exception as e:
        logger.error(f"解析遊戲資料失敗: {e}")
        return []

def run_scheduler_async():
    """異步執行排程任務（支持用戶停止）"""
    global task_status

    try:
        task_status['is_running'] = True
        task_status['start_time'] = datetime.now()
        task_status['stop_requested'] = False
        task_status['stopped_by_user'] = False

        update_task_status('開始', 0, '初始化任務...')

        logger.info("開始執行完整排程任務...")

        # 檢查是否在初始化階段就被停止
        if check_if_should_stop():
            logger.info("🛑 任務在初始化階段被停止")
            update_task_status('已停止', 0, '任務已被用戶停止')
            task_status['is_running'] = False
            task_status['stopped_by_user'] = True
            return False, "任務已被用戶停止"

        logger.info(f"🔧 當前工作目錄: {os.getcwd()}")
        logger.info(f"🔧 Python 版本: {subprocess.run(['python3', '--version'], capture_output=True, text=True).stdout.strip()}")

        # 檢查當前環境和權限
        logger.info(f"🔧 當前用戶: {os.getenv('USER', 'unknown')}")
        logger.info(f"🔧 HOME 目錄: {os.getenv('HOME', 'unknown')}")
        logger.info(f"🔧 工作目錄: {os.getcwd()}")

        # 檢查輸出目錄
        output_dir = "frontend/public/outputs"
        abs_output_dir = os.path.abspath(output_dir)
        logger.info(f"📁 輸出目錄相對路徑: {output_dir}")
        logger.info(f"📁 輸出目錄絕對路徑: {abs_output_dir}")

        if os.path.exists(output_dir):
            logger.info(f"✅ 輸出目錄存在")
            try:
                files = os.listdir(output_dir)
                logger.info(f"📂 目錄中有 {len(files)} 個檔案")
            except Exception as e:
                logger.error(f"❌ 無法列出目錄內容: {e}")
        else:
            logger.warning(f"⚠️ 輸出目錄不存在: {output_dir}")

        # 再次檢查是否被停止
        if check_if_should_stop():
            logger.info("🛑 任務在環境檢查階段被停止")
            update_task_status('已停止', 0, '任務已被用戶停止')
            task_status['is_running'] = False
            task_status['stopped_by_user'] = True
            return False, "任務已被用戶停止"

        update_task_status('準備執行', 5, '檢查環境完成，開始執行排程...')

        # 執行排程腳本，使用 Popen 來支持中途停止
        cmd = [
            'python3', 'scheduler.py', '--run-now',
            '--detail', 'all',
            '--lang', 'zh-tw'
        ]

        # 根據設定添加額外參數
        force_llm_analysis = task_status.get('force_llm_analysis', False)
        force_regenerate = task_status.get('force_regenerate', False)

        if force_llm_analysis:
            cmd.append('--force-llm-analysis')
            logger.info("🤖 啟用強制LLM分析模式")

        if force_regenerate:
            cmd.append('--force')
            logger.info("🔄 啟用強制重新產生模式")

        logger.info(f"🚀 執行命令: {' '.join(cmd)}")

        update_task_status('執行中', 10, '正在執行數據抓取和報表生成...')

        # 使用 Popen 啟動子進程
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )

        # 監控子進程並檢查停止請求
        output_lines = []
        error_lines = []
        start_time = datetime.now()
        last_progress_update = start_time
        max_runtime = 7200  # 120分鐘（2小時）超時
        warning_runtime = 5400  # 90分鐘警告

        while process.poll() is None:  # 進程還在運行
            current_time = datetime.now()
            elapsed = (current_time - task_status['start_time']).total_seconds()

            # 檢查超時
            if elapsed > max_runtime:
                logger.error(f"⏰ 任務執行超時（{max_runtime/60}分鐘），強制終止進程")
                try:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    update_task_status('超時', 0, f'任務執行超過{max_runtime/60}分鐘，已強制終止')
                    task_status['is_running'] = False
                    return False, f"任務執行超時（{max_runtime/60}分鐘）"
                except Exception as timeout_error:
                    logger.error(f"❌ 終止超時進程時發生錯誤: {timeout_error}")
                    update_task_status('錯誤', 0, '終止超時任務時發生錯誤')
                    task_status['is_running'] = False
                    return False, f"終止超時任務時發生錯誤: {timeout_error}"

            # 45分鐘警告
            elif elapsed > warning_runtime and elapsed % 300 < 2:  # 每5分鐘提醒一次
                logger.warning(f"⚠️ 任務已運行{int(elapsed/60)}分鐘，接近超時限制")

            # 檢查是否需要停止
            if check_if_should_stop():
                logger.info("🛑 收到停止請求，正在終止子進程...")
                update_task_status('停止中', task_status['progress'], '正在停止任務...')

                try:
                    # 優雅地終止進程
                    process.terminate()
                    # 等待 5 秒讓進程優雅退出
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        # 如果進程沒有優雅退出，強制終止
                        logger.warning("⚠️ 進程未能優雅退出，強制終止...")
                        process.kill()
                        process.wait()

                    logger.info("✅ 子進程已成功停止")
                    update_task_status('已停止', 0, '任務已被用戶停止')
                    task_status['is_running'] = False
                    task_status['stopped_by_user'] = True
                    return False, "任務已被用戶停止"

                except Exception as stop_error:
                    logger.error(f"❌ 停止進程時發生錯誤: {stop_error}")
                    # 即使停止失敗，也要更新狀態
                    update_task_status('停止失敗', 0, '停止任務時發生錯誤')
                    task_status['is_running'] = False
                    return False, f"停止任務時發生錯誤: {stop_error}"

            # 讀取和解析子進程輸出
            try:
                # 讀取 stdout 輸出
                while True:
                    try:
                        line = process.stdout.readline()
                        if not line:
                            break

                        line = line.strip()
                        if line:
                            output_lines.append(line)
                            logger.info(f"📋 子進程輸出: {line}")

                            # 解析實際執行狀態
                            progress, status_msg = parse_execution_progress(line, elapsed)
                            if progress is not None and status_msg:
                                update_task_status('執行中', progress, status_msg)
                                last_progress_update = current_time
                                task_status['last_specific_update'] = current_time
                            elif status_msg:
                                # 即使沒有進度數字，也更新狀態訊息
                                current_progress = task_status.get('progress', 0)
                                update_task_status('執行中', current_progress, status_msg)
                                last_progress_update = current_time

                    except Exception as stdout_error:
                        break

                # 讀取 stderr 輸出
                while True:
                    try:
                        error_line = process.stderr.readline()
                        if not error_line:
                            break

                        error_line = error_line.strip()
                        if error_line:
                            error_lines.append(error_line)
                            logger.warning(f"⚠️ 子進程錯誤: {error_line}")

                            # 解析錯誤中的有用訊息
                            progress, status_msg = parse_execution_progress(error_line, elapsed)
                            if status_msg:
                                current_progress = task_status.get('progress', 0)
                                update_task_status('執行中', current_progress, status_msg)
                                last_progress_update = current_time

                    except Exception as stderr_error:
                        break

            except Exception as read_error:
                logger.warning(f"讀取子進程輸出時發生錯誤: {read_error}")

            # 如果超過30秒沒有具體更新，顯示時間狀態
            if (current_time - last_progress_update).total_seconds() >= 30:
                time_status = f'運行中... ({int(elapsed/60)} 分鐘 {int(elapsed%60)} 秒)'
                if elapsed > warning_runtime:
                    time_status = f'⚠️ 任務運行時間較長 ({int(elapsed/60)} 分鐘)，請耐心等待...'

                current_progress = task_status.get('progress', 0)
                update_task_status('執行中', current_progress, time_status)
                last_progress_update = current_time

            # 短暫休眠，避免過度消耗 CPU
            time.sleep(0.5)

        # 子進程已完成，獲取輸出
        stdout, stderr = process.communicate()
        return_code = process.returncode

        logger.info(f"📊 命令執行完成，返回碼: {return_code}")

        if stdout:
            logger.info("📝 標準輸出:")
            for line in stdout.split('\n'):
                if line.strip():
                    logger.info(f"  STDOUT: {line}")

        if stderr:
            logger.info("⚠️ 標準錯誤:")
            for line in stderr.split('\n'):
                if line.strip():
                    logger.info(f"  STDERR: {line}")

        # 最後檢查是否被停止（以防在進程結束後立即被停止）
        if check_if_should_stop():
            logger.info("🛑 任務在完成檢查階段被停止")
            update_task_status('已停止', 0, '任務已被用戶停止')
            task_status['is_running'] = False
            task_status['stopped_by_user'] = True
            return False, "任務已被用戶停止"

        if return_code == 0:
            update_task_status('檢查結果', 90, '排程執行成功，檢查產生的檔案...')

            logger.info("✅ 排程任務執行成功")

            # 檢查報表檔案是否實際產生
            report_dir = "frontend/public/outputs"
            logger.info(f"🔍 檢查報表目錄: {report_dir}")

            if os.path.exists(report_dir):
                files = os.listdir(report_dir)
                logger.info(f"📂 目錄中的檔案數量: {len(files)}")

                # 列出最近的幾個檔案
                if files:
                    sorted_files = sorted(files, reverse=True)[:5]
                    logger.info("📄 最近的報表檔案:")
                    for f in sorted_files:
                        file_path = os.path.join(report_dir, f)
                        file_size = os.path.getsize(file_path)
                        file_mtime = os.path.getmtime(file_path)
                        import datetime as dt
                        mtime_str = dt.datetime.fromtimestamp(file_mtime).strftime('%Y-%m-%d %H:%M:%S')
                        logger.info(f"  📄 {f} ({file_size} bytes, {mtime_str})")

                    # 檢查今日報表
                    today = datetime.now().strftime("%Y-%m-%d")
                    today_reports = [f for f in files if f.startswith(f"report-{today}")]
                    logger.info(f"📄 今日報表檔案: {today_reports}")

                    if today_reports:
                        update_task_status('完成', 100, f'成功產生 {len(today_reports)} 個今日報表檔案')
                        task_status['is_running'] = False
                        return True, "排程任務執行成功，報表已產生"
                    else:
                        update_task_status('警告', 95, '排程執行成功但未發現今日報表檔案')
                        task_status['is_running'] = False
                        return True, "排程任務執行成功，但請檢查報表檔案"
                else:
                    logger.warning("⚠️ 報表目錄為空！")
                    update_task_status('警告', 90, '排程執行成功但報表目錄為空')
            else:
                logger.error(f"❌ 報表目錄不存在: {report_dir}")
                update_task_status('錯誤', 85, '報表目錄不存在')

            task_status['is_running'] = False
            return True, "排程任務執行成功"
        else:
            logger.error(f"❌ 排程任務執行失敗，返回碼: {return_code}")
            update_task_status('失敗', 0, f'排程執行失敗: {stderr[:100] if stderr else "未知錯誤"}...')
            task_status['is_running'] = False
            return False, f"排程任務執行失敗: {stderr}"

    except Exception as e:
        logger.error(f"💥 排程任務執行異常: {e}")
        import traceback
        logger.error(f"💥 異常堆疊: {traceback.format_exc()}")
        update_task_status('異常', 0, f'執行異常: {str(e)[:100]}...')
        task_status['is_running'] = False
        return False, f"排程任務執行異常: {e}"

def run_scheduler():
    """執行完整的排程任務 (保持同步介面兼容性)"""
    return run_scheduler_async()

def generate_report(force_llm_analysis=False, force_regenerate=False):
    """產生新的報表"""
    try:
        logger.info(f"開始產生報表... 強制LLM分析: {force_llm_analysis}, 強制重新產生: {force_regenerate}")

        # 檢查是否已有任務在運行
        if task_status['is_running']:
            elapsed = (datetime.now() - task_status['start_time']).total_seconds() if task_status['start_time'] else 0
            return True, f"報表產生中... 已運行 {int(elapsed/60)} 分鐘，當前步驟: {task_status['current_step']}"

        # 重置任務狀態，清除之前的停止標誌
        reset_task_status()

        # 儲存設定參數到全域變數
        task_status['force_llm_analysis'] = force_llm_analysis
        task_status['force_regenerate'] = force_regenerate

        # 啟動異步任務
        thread = threading.Thread(target=run_scheduler_async)
        thread.daemon = True
        thread.start()

        options_text = []
        if force_llm_analysis:
            options_text.append("強制LLM分析")
        if force_regenerate:
            options_text.append("強制重新產生")

        message = "報表產生任務已啟動"
        if options_text:
            message += f"（{', '.join(options_text)}）"
        message += "，請稍後檢查進度"

        return True, message

    except Exception as e:
        logger.error(f"報表產生異常: {e}")
        import traceback
        logger.error(f"異常堆疊: {traceback.format_exc()}")
        return False, f"報表產生異常: {e}"


@app.route('/settings')
@login_required
def settings():
    """設定頁面"""
    available_dates = get_available_dates()
    bgg_username = get_app_setting('bgg_username', '')
    user = session.get('user', {})
    return render_template('settings.html',
                           available_dates=available_dates,
                           bgg_username=bgg_username,
                           user=user,
                           rg_model_dir=RG_DEFAULT_MODEL_DIR,
                           rg_games_file=RG_DEFAULT_GAMES_FILE,
                           rg_ratings_file=RG_DEFAULT_RATINGS_FILE,
                           last_updated=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

@app.route('/api/save-settings', methods=['POST'])
@login_required
def api_save_settings():
    
    try:
        data = request.get_json() or {}
        bgg_username = data.get('bgg_username', '').strip()
        
        if not bgg_username:
            return jsonify({'success': False, 'message': '請輸入 BGG 使用者名稱'}), 400
        
        # 驗證 BGG 使用者名稱格式（基本檢查）
        if len(bgg_username) < 3 or len(bgg_username) > 50:
            return jsonify({'success': False, 'message': 'BGG 使用者名稱長度需在 3-50 字元之間'}), 400
        
        logger.info(f"嘗試保存 BGG 使用者名稱: {bgg_username}")
        ok = set_app_setting('bgg_username', bgg_username)
        
        if ok:
            logger.info(f"✅ BGG 使用者名稱保存成功: {bgg_username}")
            return jsonify({'success': True, 'message': '設定已儲存'})
        else:
            logger.error(f"❌ BGG 使用者名稱保存失敗: {bgg_username}")
            return jsonify({'success': False, 'message': '儲存失敗，請檢查資料庫連接'}), 500
            
    except Exception as e:
        logger.error(f"保存設定時發生異常: {e}")
        return jsonify({'success': False, 'message': f'保存失敗: {str(e)}'}), 500

@app.route('/api/sync-collection', methods=['POST'])
def api_sync_collection():
    if 'logged_in' not in session:
        return jsonify({'success': False, 'message': '未登入'}), 401
    username = get_app_setting('bgg_username')
    if not username:
        return jsonify({'success': False, 'message': '請先在設定頁設定 BGG 使用者名稱'}), 400
    try:
        # 兩段式呼叫：先 boardgame（排除 expansion），再 expansion
        xml_main = fetch_bgg_collection_xml(username, {"stats": 1, "excludesubtype": "boardgameexpansion"})
        xml_exp = fetch_bgg_collection_xml(username, {"stats": 1, "subtype": "boardgameexpansion"})
        items = parse_bgg_collection(xml_main) + parse_bgg_collection(xml_exp)
        written = upsert_collection_items(items)
        return jsonify({'success': True, 'message': f'同步完成，共 {written} 筆'})
    except TimeoutError as te:
        return jsonify({'success': False, 'message': f'BGG 排隊中，請稍後再試：{te}'}), 502
    except Exception as e:
        logger.error(f"同步收藏失敗: {e}")
        return jsonify({'success': False, 'message': f'同步失敗：{e}'}), 500

@app.route('/recommendations')
def recommendations():
    if 'logged_in' not in session:
        return redirect(url_for('login'))
    username = get_app_setting('bgg_username', '')
    if not username:
        flash('請先在設定頁設定 BGG 使用者名稱並同步收藏', 'info')
        return redirect(url_for('settings'))
    recs = build_recommendations_from_collection(limit=30)
    return render_template('recommendations.html', recommendations=recs, bgg_username=username,
                           last_updated=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

@app.route('/rg-recommender')
def rg_recommender():
    if 'logged_in' not in session:
        return redirect(url_for('login'))
    username = get_app_setting('bgg_username', '')
    # 讀取已收藏的 objectid 清單，供外部 API（若有）使用
    owned_ids = []
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT objectid FROM collection")
            owned_ids = [row[0] for row in cursor.fetchall()]
    except Exception:
        pass

    rg_results = None
    rg_error = None
    
    # 首先嘗試使用進階推薦器
    try:
        # 檢查是否有算法參數（從 URL 參數或 session 中獲取）
        from flask import request
        algorithm = request.args.get('algorithm', 'hybrid')
        
        rg_results = get_advanced_recommendations(username, owned_ids, algorithm=algorithm, limit=30)
        if not rg_results:
            logger.info("進階推薦器沒有結果，嘗試基礎推薦器")
            rg_results = get_local_recommendations(username, owned_ids, limit=30)
        if not rg_results:
            logger.info("本地推薦器沒有結果，嘗試外部 API")
    except Exception as e:
        logger.error(f"進階推薦器發生錯誤: {e}")
        rg_error = f"推薦器錯誤: {str(e)}"
    
    # 如果本地推薦失敗且有外部 API，則嘗試外部 API
    if not rg_results and username and RG_API_URL:
        external_results, external_error = call_recommend_games_api(username, owned_ids, limit=30)
        if external_results:
            rg_results = external_results
        elif external_error and not rg_error:
            rg_error = external_error

    # 傳遞可用的算法選項
    available_algorithms = [
        {'value': 'hybrid', 'name': '混合推薦 (Hybrid)', 'description': '結合多種算法的推薦'},
        {'value': 'popularity', 'name': '熱門推薦 (Popularity)', 'description': '基於遊戲熱門度的推薦'},
        {'value': 'content', 'name': '內容推薦 (Content-based)', 'description': '基於遊戲特徵相似性的推薦'}
    ]
    
    current_algorithm = request.args.get('algorithm', 'hybrid')
    
    return render_template('rg_recommender.html',
                           bgg_username=username,
                           rg_results=rg_results,
                           rg_error=rg_error,
                           available_algorithms=available_algorithms,
                           current_algorithm=current_algorithm,
                           rg_site_url='https://recommend.games/',
                           rg_repo_url='https://gitlab.com/recommend.games/board-game-recommender',
                           last_updated=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

@app.route('/api/rg-train', methods=['POST'])
def api_rg_train():
    if 'logged_in' not in session:
        return jsonify({'success': False, 'message': '未登入'}), 401
    # 使用固定預設路徑
    model_dir = RG_DEFAULT_MODEL_DIR
    games_file = RG_DEFAULT_GAMES_FILE
    ratings_file = RG_DEFAULT_RATINGS_FILE
    # 檢查並安裝 board-game-recommender
    try:
        import importlib.util
        spec = importlib.util.find_spec('board_game_recommender')
        if spec is None:
            # 嘗試安裝 board-game-recommender
            logger.info("正在安裝 board-game-recommender...")
            install_cmd = [sys.executable, '-m', 'pip', 'install', 'board-game-recommender']
            install_proc = subprocess.run(install_cmd, capture_output=True, text=True)
            if install_proc.returncode != 0:
                return jsonify({'success': False, 'message': f'安裝 board-game-recommender 失敗: {install_proc.stderr}'}), 400
            logger.info("board-game-recommender 安裝成功")
    except Exception as e:
        return jsonify({'success': False, 'message': f'檢查模組時發生錯誤: {str(e)}'}), 400

    # 執行訓練命令 - 改用直接 import 方式避免 __main__ 問題
    try:
        # 先嘗試使用模組的 API
        try:
            import board_game_recommender
            # 如果模組有訓練函數，直接呼叫
            if hasattr(board_game_recommender, 'train'):
                result = board_game_recommender.train(
                    games_file=games_file,
                    ratings_file=ratings_file,
                    model_dir=model_dir
                )
                return jsonify({'success': True, 'message': '訓練完成', 'result': str(result)})
        except (ImportError, AttributeError):
            pass  # 繼續使用 CLI 方式

        # 使用 LightGamesRecommender 直接訓練
        from board_game_recommender.light import LightGamesRecommender
        import os
        
        # 確保模型目錄存在
        os.makedirs(model_dir, exist_ok=True)
        
        # 檢查輸入檔案是否存在，如果不存在則從 BGG 直接抓取
        if not os.path.exists(games_file) or not os.path.exists(ratings_file):
            logger.info("從 BGG 直接抓取用戶資料...")
            
            # 獲取 BGG 用戶名
            username = get_app_setting('bgg_username')
            if not username:
                return jsonify({'success': False, 'message': '請先在設定頁面輸入 BGG 用戶名'})
            
            try:
                from bgg_scraper_extractor import BGGScraperExtractor
                extractor = BGGScraperExtractor()
                success = extractor.export_to_jsonl(username)
                if not success:
                    return jsonify({'success': False, 'message': f'無法從 BGG 抓取用戶 {username} 的資料'})
                logger.info(f"成功從 BGG 抓取用戶 {username} 的資料")
            except Exception as e:
                logger.error(f"從 BGG 抓取資料時發生錯誤: {e}")
                return jsonify({'success': False, 'message': f'資料抓取失敗: {str(e)}'})
        
        logger.info(f"開始 RG 訓練: games={games_file}, ratings={ratings_file}, model={model_dir}")
        
        # 檢查是否有現有模型，如果沒有則創建基礎推薦器
        model_file = os.path.join(model_dir, 'recommender.npz')
        
        if os.path.exists(model_file):
            # 載入現有模型
            try:
                recommender = LightGamesRecommender.from_npz(model_file)
                logger.info(f"載入現有模型: {model_file}")
                return jsonify({
                    'success': True,
                    'message': f'成功載入現有推薦模型！用戶數: {recommender.num_users}, 遊戲數: {recommender.num_games}'
                })
            except Exception as e:
                logger.error(f"載入模型失敗: {e}")
        
        # 如果沒有現有模型，創建簡單的基準推薦器
        from board_game_recommender.baseline import PopularGamesRecommender
        import pandas as pd
        import numpy as np
        
        # 讀取資料並創建基準推薦器
        try:
            # 讀取評分資料
            ratings_data = []
            with open(ratings_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        rating = json.loads(line)
                        ratings_data.append(rating)
            
            # 轉換為 DataFrame
            df = pd.DataFrame(ratings_data)
            
            # 計算每個遊戲的平均評分和評分數量
            game_stats = df.groupby('game_id').agg({
                'rating': ['mean', 'count']
            }).round(2)
            game_stats.columns = ['avg_rating', 'num_ratings']
            game_stats = game_stats.reset_index()
            
            # 計算熱門度分數（結合平均評分和評分數量）
            # 使用貝葉斯平均來處理評分數量較少的遊戲
            global_mean = df['rating'].mean()
            min_votes = 3  # 最少需要3個評分才考慮
            
            def bayesian_average(row):
                avg_rating = row['avg_rating']
                num_ratings = row['num_ratings']
                return (num_ratings * avg_rating + min_votes * global_mean) / (num_ratings + min_votes)
            
            game_stats['popularity_score'] = game_stats.apply(bayesian_average, axis=1)
            
            # 準備推薦器所需的資料
            game_ids = [int(gid) for gid in game_stats['game_id'].tolist()]
            scores = game_stats['popularity_score'].values
            
            # 創建基準推薦器
            recommender = PopularGamesRecommender(
                game_ids=game_ids,
                scores=scores,
                default_value=global_mean
            )
            
            # 保存模型
            model_file = os.path.join(model_dir, 'popular_recommender.json')
            model_data = {
                'type': 'PopularGamesRecommender',
                'game_ids': game_ids,
                'scores': scores.tolist(),
                'default_value': float(global_mean),
                'num_games': len(game_ids),
                'num_ratings': len(df)
            }
            with open(model_file, 'w', encoding='utf-8') as f:
                json.dump(model_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"創建基準推薦器成功，資料包含 {len(df)} 個評分")
            
            return jsonify({
                'success': True,
                'message': f'✅ 推薦器訓練完成！處理了 {len(df)} 個評分，{df["game_id"].nunique()} 個遊戲，{df["user_id"].nunique()} 個用戶。模型已保存到 {model_file}',
                'stats': {
                    'num_games': len(game_ids),
                    'num_ratings': len(df),
                    'num_users': df["user_id"].nunique(),
                    'avg_rating': round(global_mean, 2),
                    'model_type': 'PopularGamesRecommender'
                }
            })
            
        except Exception as e:
            logger.error(f"創建推薦器時發生錯誤: {e}")
            return jsonify({
                'success': False,
                'message': f'創建推薦器失敗: {str(e)}'
            })
    except Exception as e:
        logger.error(f"RG 訓練異常: {e}")
        return jsonify({'success': False, 'message': f'訓練異常：{e}'})

@app.route('/api/rg-status', methods=['GET'])
def api_rg_status():
    if 'logged_in' not in session:
        return jsonify({'success': False, 'message': '未登入'}), 401
    model_dir = RG_DEFAULT_MODEL_DIR
    games_file = RG_DEFAULT_GAMES_FILE
    ratings_file = RG_DEFAULT_RATINGS_FILE
    status = {
        'rg_model_dir': model_dir,
        'rg_games_file': games_file,
        'rg_ratings_file': ratings_file,
        'model_dir_exists': bool(model_dir and os.path.exists(model_dir)),
        'games_file_exists': bool(games_file and os.path.exists(games_file)),
        'ratings_file_exists': bool(ratings_file and os.path.exists(ratings_file)),
        'rg_api_url': RG_API_URL or '',
        'defaults': {
            'games_file': RG_DEFAULT_GAMES_FILE,
            'ratings_file': RG_DEFAULT_RATINGS_FILE,
            'model_dir': RG_DEFAULT_MODEL_DIR
        }
    }
    return jsonify({'success': True, 'status': status})

@app.route('/api/rg-scrape', methods=['POST'])
def api_rg_scrape():
    if 'logged_in' not in session:
        return jsonify({'success': False, 'message': '未登入'}), 401
    if rg_task_status.get('is_running'):
        return jsonify({'success': False, 'message': '已有抓取任務在進行中'}), 400
    # 採用固定預設輸出路徑
    games_file = RG_DEFAULT_GAMES_FILE
    ratings_file = RG_DEFAULT_RATINGS_FILE
    # 檢查是否設定了 BGG 用戶名
    bgg_username = get_app_setting('bgg_username')
    if not bgg_username:
        return jsonify({'success': False, 'message': '請先在設定頁面輸入 BGG 用戶名'}), 400

    # 確保輸出目錄存在
    try:
        if games_file:
            os.makedirs(os.path.dirname(games_file), exist_ok=True)
        if ratings_file:
            os.makedirs(os.path.dirname(ratings_file), exist_ok=True)
    except Exception:
        pass

    # 啟動背景任務
    rg_task_status.update({'is_running': True, 'start_time': datetime.now(), 'progress': 0, 'message': '啟動中', 'stdout_tail': [], 'stderr_tail': []})
    thread = threading.Thread(target=run_rg_scrape_async, args=(games_file, ratings_file, None))
    thread.daemon = True
    thread.start()
    return jsonify({'success': True, 'message': '抓取任務已啟動'})

@app.route('/api/rg-task-status', methods=['GET'])
def api_rg_task_status():
    if 'logged_in' not in session:
        return jsonify({'success': False, 'message': '未登入'}), 401
    st = rg_task_status.copy()
    st['elapsed_seconds'] = int((datetime.now() - st['start_time']).total_seconds()) if st.get('start_time') else 0
    # 只回傳 tail 以防過大
    st['stdout_tail'] = st.get('stdout_tail', [])[-20:]
    st['stderr_tail'] = st.get('stderr_tail', [])[-20:]
    if st.get('last_update'):
        st['last_update'] = st['last_update'].isoformat()
    return jsonify({'success': True, 'status': st})

@app.route('/api/task-status', methods=['GET'])
def api_task_status():
    """API端點：查詢任務狀態"""
    if 'logged_in' not in session:
        return jsonify({'success': False, 'message': '未登入'}), 401

    global task_status

    # 計算運行時間
    elapsed_seconds = 0
    if task_status['start_time']:
        elapsed_seconds = (datetime.now() - task_status['start_time']).total_seconds()

    return jsonify({
        'success': True,
        'status': {
            'is_running': task_status['is_running'],
            'current_step': task_status['current_step'],
            'progress': task_status['progress'],
            'message': task_status['message'],
            'elapsed_seconds': int(elapsed_seconds),
            'elapsed_minutes': int(elapsed_seconds / 60),
            'last_update': task_status['last_update'].isoformat() if task_status['last_update'] else None,
            'stop_requested': task_status.get('stop_requested', False),
            'stopped_by_user': task_status.get('stopped_by_user', False)
        }
    })

@app.route('/api/run-scheduler', methods=['POST'])
def api_run_scheduler():
    """API端點：執行完整排程任務"""
    if 'logged_in' not in session:
        return jsonify({'success': False, 'message': '未登入'}), 401

    # 解析請求參數
    data = request.get_json() or {}
    force_llm_analysis = data.get('force_llm_analysis', False)
    force_regenerate = data.get('force_regenerate', False)

    logger.info(f"收到報表產生請求 - 強制LLM分析: {force_llm_analysis}, 強制重新產生: {force_regenerate}")

    success, message = generate_report(force_llm_analysis=force_llm_analysis, force_regenerate=force_regenerate)
    return jsonify({'success': success, 'message': message})

@app.route('/api/cron-trigger', methods=['POST'])
def api_cron_trigger():
    """外部 Cron 服務觸發端點（無需登入）"""
    # 檢查請求來源的安全性
    auth_header = request.headers.get('Authorization')
    expected_token = os.getenv('CRON_SECRET_TOKEN', 'default-cron-secret')

    if not auth_header or auth_header != f'Bearer {expected_token}':
        logger.warning(f"未授權的 cron 觸發請求，來源 IP: {request.remote_addr}")
        return jsonify({'success': False, 'message': '未授權'}), 401

    logger.info(f"收到外部 Cron 觸發請求，來源 IP: {request.remote_addr}")
    
    # 檢查是否已有任務正在執行
    if task_status['is_running']:
        logger.info("已有任務正在執行，跳過此次觸發")
        return jsonify({
            'success': True, 
            'message': '任務已在執行中',
            'status': 'already_running',
            'current_step': task_status.get('current_step', ''),
            'progress': task_status.get('progress', 0)
        })

    try:
        # 非同步執行報表產生，立即回應成功
        def async_report_generation():
            try:
                logger.info("🚀 開始非同步報表產生")
                from scheduler import fetch_and_generate_report
                
                # 更新任務狀態
                global task_status
                task_status.update({
                    'is_running': True,
                    'start_time': datetime.now(),
                    'current_step': '初始化',
                    'progress': 0,
                    'message': '開始產生報表...',
                    'last_update': datetime.now(),
                    'stop_requested': False,
                    'stopped_by_user': False
                })
                
                result = fetch_and_generate_report('all', 'zh-tw', False, False)
                
                # 完成任務
                task_status.update({
                    'is_running': False,
                    'current_step': '完成',
                    'progress': 100,
                    'message': '報表產生完成' if result else '報表產生失敗',
                    'last_update': datetime.now()
                })
                
                if result:
                    logger.info("✅ 非同步 Cron 觸發的報表產生成功")
                else:
                    logger.error("❌ 非同步 Cron 觸發的報表產生失敗")
                    
            except Exception as e:
                logger.error(f"❌ 非同步報表產生異常: {e}")
                task_status.update({
                    'is_running': False,
                    'current_step': '錯誤',
                    'progress': 0,
                    'message': f'執行失敗: {str(e)}',
                    'last_update': datetime.now()
                })

        # 啟動背景執行緒
        import threading
        thread = threading.Thread(target=async_report_generation)
        thread.daemon = True
        thread.start()
        
        logger.info("✅ Cron 觸發已接受，報表產生已在背景執行")
        return jsonify({
            'success': True, 
            'message': '報表產生已啟動',
            'status': 'started',
            'info': '任務正在背景執行，請稍後查看結果'
        })

    except Exception as e:
        logger.error(f"❌ Cron 觸發處理異常: {e}")
        return jsonify({'success': False, 'message': f'處理失敗: {str(e)}'}), 500

@app.route('/api/diagnose-recommendations', methods=['GET'])
def api_diagnose_recommendations():
    """診斷推薦系統狀態（用於 Zeabur 調試）"""
    if 'logged_in' not in session:
        return jsonify({'success': False, 'message': '未登入'}), 401
    
    diagnosis = {}
    
    try:
        # 基本資料檢查
        username = get_app_setting('bgg_username', '')
        diagnosis['bgg_username'] = username or 'None'
        
        # 檢查收藏資料
        owned_ids = []
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT objectid FROM collection")
                owned_ids = [row[0] for row in cursor.fetchall()]
            diagnosis['owned_games_count'] = len(owned_ids)
            diagnosis['owned_games_sample'] = owned_ids[:5] if owned_ids else []
        except Exception as e:
            diagnosis['collection_error'] = str(e)
        
        # 檢查進階推薦器
        try:
            from advanced_recommender import AdvancedBoardGameRecommender
            recommender = AdvancedBoardGameRecommender()
            
            diagnosis['database_exists'] = recommender.check_database_connection()
            diagnosis['tables_exist'] = recommender.check_tables_exist()
            
            if recommender.load_data():
                diagnosis['games_count'] = len(recommender.games_df)
                diagnosis['ratings_count'] = len(recommender.ratings_df)
                
                # 嘗試簡單的熱門度推薦
                recommender.prepare_user_item_matrix()
                recommender.prepare_content_features()
                recommender.train_popularity_recommender()
                
                pop_recs = recommender.recommend_popularity([], 3)
                diagnosis['sample_popularity_recommendations'] = [
                    {'name': rec['name'], 'score': rec['rec_score']} 
                    for rec in pop_recs[:3]
                ] if pop_recs else []
                
                # 嘗試混合推薦
                recommender.train_all_models()
                hybrid_recs = recommender.recommend_hybrid(owned_ids[:5], 3)
                diagnosis['sample_hybrid_recommendations'] = [
                    {'name': rec['name'], 'score': rec['rec_score']} 
                    for rec in hybrid_recs[:3]
                ] if hybrid_recs else []
                
            else:
                diagnosis['data_load_failed'] = True
                
        except Exception as e:
            diagnosis['advanced_recommender_error'] = str(e)
            import traceback
            diagnosis['advanced_recommender_traceback'] = traceback.format_exc()
        
        # 測試完整推薦流程
        try:
            test_recs = get_advanced_recommendations(username, owned_ids[:5], 'popularity', 3)
            diagnosis['full_recommendation_test'] = {
                'success': test_recs is not None,
                'count': len(test_recs) if test_recs else 0,
                'sample': [rec['name'] for rec in test_recs[:3]] if test_recs else []
            }
        except Exception as e:
            diagnosis['full_recommendation_error'] = str(e)
        
        return jsonify({
            'success': True,
            'diagnosis': diagnosis,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        })

@app.route('/api/stop-task', methods=['POST'])
def api_stop_task():
    """API端點：停止當前執行的任務"""
    if 'logged_in' not in session:
        logger.warning("未登入用戶嘗試停止任務")
        return jsonify({'success': False, 'message': '未登入'}), 401

    try:
        logger.info(f"收到停止任務請求，當前任務狀態: is_running={task_status['is_running']}")

        if not task_status['is_running']:
            logger.info("沒有運行中的任務需要停止")
            return jsonify({
                'success': False,
                'message': '目前沒有運行中的任務'
            })

        # 請求停止任務
        stopped = request_task_stop()

        if stopped:
            logger.info("🛑 停止請求已成功發送")
            return jsonify({
                'success': True,
                'message': '停止請求已發送，任務正在停止中...'
            })
        else:
            logger.error("停止任務請求失敗")
            return jsonify({
                'success': False,
                'message': '無法停止任務'
            })

    except Exception as e:
        logger.error(f"停止任務 API 發生異常: {e}")
        import traceback
        logger.error(f"異常堆疊: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'message': f'停止任務時發生錯誤: {e}'
        })


@app.route('/')
def index():
    """首頁 - 重導向到登入或儀表板"""
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login')
@app.route('/login_email')
def login():
    """顯示登入頁面"""
    if 'user' in session:
        return redirect(url_for('dashboard'))
    
    # 使用新的 email 登入模板
    return render_template('login_email.html')

@app.route('/auth/google')
def google_auth_callback():
    """處理 Google 登入回調"""
    if not GOOGLE_AUTH_AVAILABLE or not google_auth:
        flash('Google 登入功能暫不可用', 'error')
        return redirect(url_for('login'))
    
    token = request.args.get('token')
    if not token:
        flash('登入失敗：未收到認證 token', 'error')
        return redirect(url_for('login'))
    
    # 驗證 Google token
    user_info = google_auth.verify_google_token(token)
    if not user_info:
        flash('登入失敗：無效的認證 token', 'error')
        return redirect(url_for('login'))
    
    if not user_info['email_verified']:
        flash('登入失敗：請先驗證您的 Google 帳戶 email', 'error')
        return redirect(url_for('login'))
    
    # 創建或更新用戶
    user_data = google_auth.create_or_update_user(
        user_info['google_id'],
        user_info['email'],
        user_info['name'],
        user_info['picture']
    )
    
    if user_data:
        session['user'] = user_data
        session['logged_in'] = True
        session['user_email'] = user_data.get('email', '')
        flash(f'歡迎 {user_data["name"]}！', 'success')
        return redirect(url_for('dashboard'))
    else:
        flash('登入失敗：無法創建用戶資料', 'error')
        return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    """用戶儀表板"""
    return render_template('reports.html')

@app.route('/generate')
@admin_required
def generate():

    success, message = generate_report()
    if success:
        flash(message, 'success')
    else:
        flash(message, 'error')

    return redirect(url_for('index'))


@app.route('/bgg_times')
def bgg_times():
    """復古報紙風格的報表檢視 - 真正的舊報紙風格"""
    if 'logged_in' not in session:
        return redirect(url_for('login'))

    # 獲取選擇的日期，預設為今日
    selected_date = request.args.get('date')
    if not selected_date:
        selected_date = datetime.now().strftime('%Y-%m-%d')

    # 獲取指定日期的報表
    content, filename = get_report_by_date(selected_date)

    # 如果找不到指定日期的報表，嘗試獲取最新報表
    if content is None:
        content, filename = get_latest_report()

    if content is None:
        return render_template('error.html', error=filename)

    # 解析所有遊戲資料
    all_games = parse_game_data_from_report(content)
    current_page_games = all_games
    total_games = len(all_games)

    # 獲取所有可用日期
    available_dates = get_available_dates()

    return render_template('bgg_times.html',
                         current_page_games=current_page_games,
                         filename=filename,
                         selected_date=selected_date,
                         available_dates=available_dates,
                         total_games=total_games,
                         last_updated=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

@app.route('/api/check-files', methods=['GET'])
def api_check_files():
    """API端點：檢查報表目錄檔案"""
    if 'logged_in' not in session:
        return jsonify({'success': False, 'message': '未登入'}), 401

    try:
        report_dir = 'frontend/public/outputs'
        files_info = []

        if os.path.exists(report_dir):
            files = sorted(os.listdir(report_dir), reverse=True)
            for filename in files:
                if filename.endswith('.md'):
                    filepath = os.path.join(report_dir, filename)
                    stat = os.stat(filepath)
                    files_info.append({
                        'name': filename,
                        'size': stat.st_size,
                        'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                    })

        return jsonify({
            'success': True,
            'directory': report_dir,
            'files': files_info,
            'total_files': len(files_info)
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/check-database', methods=['GET'])
def api_check_database():
    """API端點：檢查資料庫內容"""
    if 'logged_in' not in session:
        return jsonify({'success': False, 'message': '未登入'}), 401

    try:
        # 先檢查資料庫配置
        config = get_database_config()

        # 檢查環境變數
        env_vars = {
            'DATABASE_URL': os.getenv('DATABASE_URL', 'Not set'),
            'POSTGRES_CONNECTION_STRING': os.getenv('POSTGRES_CONNECTION_STRING', 'Not set'),
            'POSTGRES_HOST': os.getenv('POSTGRES_HOST', 'Not set'),
            'POSTGRES_PORT': os.getenv('POSTGRES_PORT', 'Not set'),
            'POSTGRES_DATABASE': os.getenv('POSTGRES_DATABASE', 'Not set'),
            'POSTGRES_USERNAME': os.getenv('POSTGRES_USERNAME', 'Not set'),
            'POSTGRES_PASSWORD': os.getenv('POSTGRES_PASSWORD', 'Not set')
        }

        with get_db_connection() as conn:
            cursor = conn.cursor()

            # 檢查現有表格
            existing_tables = []
            cursor.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name
            """)

            existing_tables = [row[0] for row in cursor.fetchall()]

            # 嘗試檢查 hot_games 表（如果存在）
            hot_games_data = []
            game_detail_count = 0
            forum_threads_count = 0

            if 'hot_games' in existing_tables:
                try:
                    cursor.execute("SELECT snapshot_date, COUNT(*) as count FROM hot_games GROUP BY snapshot_date ORDER BY snapshot_date DESC LIMIT 10")
                    hot_games_data = [{'date': row[0], 'count': row[1]} for row in cursor.fetchall()]
                except Exception as e:
                    hot_games_data = [{'error': f'Query failed: {str(e)}'}]

            if 'game_detail' in existing_tables:
                try:
                    cursor.execute("SELECT COUNT(*) as total_games FROM game_detail")
                    game_detail_count = cursor.fetchone()[0]
                except:
                    pass

            if 'forum_threads' in existing_tables:
                try:
                    cursor.execute("SELECT COUNT(*) as total_threads FROM forum_threads")
                    forum_threads_count = cursor.fetchone()[0]
                except:
                    pass

            return jsonify({
                'success': True,
                'database_type': config['type'],
                'database_url_masked': config.get('url', 'Not available')[:50] + '...' if config.get('url') else 'Not available',
                'environment_variables': env_vars,
                'existing_tables': existing_tables,
                'hot_games_by_date': hot_games_data,
                'total_game_details': game_detail_count,
                'total_forum_threads': forum_threads_count
            })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e),
            'database_type': config.get('type', 'unknown') if 'config' in locals() else 'unknown',
            'environment_variables': {
                'DATABASE_URL': os.getenv('DATABASE_URL', 'Not set'),
                'POSTGRES_CONNECTION_STRING': os.getenv('POSTGRES_CONNECTION_STRING', 'Not set')
            }
        })

@app.route('/health')
def health():
    """健康檢查端點 - 快速響應版本"""
    
    # 簡單健康檢查，不阻塞啟動
    health_info = {
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'python_version': sys.version,
        'port': os.getenv('PORT', 'not set'),
        'database_url_configured': 'yes' if os.getenv('DATABASE_URL') else 'no'
    }
    
    # 只有在應用已經完全啟動後才嘗試資料庫檢查
    if os.getenv('SKIP_DB_HEALTH_CHECK') != '1':
        # 非阻塞式資料庫狀態檢查
        try:
            from database import get_db_connection
            import signal
            
            # 設置 5 秒超時
            def timeout_handler(signum, frame):
                raise TimeoutError("Database connection timeout")
            
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(5)  # 5 秒超時
            
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                health_info['database'] = 'connected'
            
            signal.alarm(0)  # 取消超時
            
        except TimeoutError:
            health_info['database'] = 'timeout'
        except Exception as e:
            health_info['database'] = f'error: {str(e)[:50]}'
    else:
        health_info['database'] = 'check_skipped'
    
    return health_info

@app.route('/health/quick')
def health_quick():
    """快速健康檢查端點 - 僅用於啟動時檢查"""
    return {
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'app': 'running'
    }

@app.route('/api/init-database', methods=['POST'])
def api_init_database():
    """手動初始化資料庫端點"""
    try:
        # 檢查是否有授權 token
        auth_header = request.headers.get('Authorization')
        expected_token = os.getenv('CRON_SECRET_TOKEN', 'default-cron-secret')
        
        if not auth_header or auth_header != f'Bearer {expected_token}':
            return jsonify({
                'success': False, 
                'message': '未授權訪問',
                'timestamp': datetime.now().isoformat()
            }), 401
        
        print("🗃️ [API] 開始手動資料庫初始化...")
        print(f"🗃️ [API] 時間戳: {datetime.now().isoformat()}")
        
        # 獲取資料庫配置
        from database import get_database_config, init_database
        config = get_database_config()
        print(f"🗃️ [API] 資料庫類型: {config['type']}")
        
        # 執行初始化
        init_database()
        
        # 驗證關鍵表是否存在
        from database import get_db_connection
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 檢查 users 表的 name 欄位
            try:
                cursor.execute("SELECT name FROM users LIMIT 1")
                users_name_exists = True
            except Exception as e:
                users_name_exists = False
                print(f"⚠️ [API] users.name 欄位檢查失敗: {e}")
            
            # 檢查 verification_codes 表
            try:
                cursor.execute("SELECT COUNT(*) FROM verification_codes")
                verification_codes_exists = True
            except Exception as e:
                verification_codes_exists = False
                print(f"⚠️ [API] verification_codes 表檢查失敗: {e}")
        
        result = {
            'success': True,
            'message': '資料庫初始化完成',
            'timestamp': datetime.now().isoformat(),
            'database_type': config['type'],
            'tables_verified': {
                'users_name_column': users_name_exists,
                'verification_codes_table': verification_codes_exists
            }
        }
        
        print(f"✅ [API] 資料庫初始化結果: {result}")
        return jsonify(result)
        
    except Exception as e:
        error_msg = f"資料庫初始化失敗: {str(e)}"
        print(f"❌ [API] {error_msg}")
        import traceback
        traceback.print_exc()
        
        return jsonify({
            'success': False,
            'message': error_msg,
            'timestamp': datetime.now().isoformat()
        }), 500

# 設計師/繪師追蹤相關路由
@app.route('/creator-tracker')
@full_access_required
def creator_tracker():
    """設計師/繪師追蹤頁面"""
    user = session.get('user', {})
    user_email = user.get('email', '')
    return render_template('creator_tracker.html', user_email=user_email)

@app.route('/api/creators/search', methods=['POST'])
@full_access_required
def api_search_creators():
    """搜尋設計師/繪師 API"""
    try:
        data = request.get_json()
        query = data.get('query', '').strip()
        creator_type = data.get('type', 'boardgamedesigner')
        
        if not query:
            return jsonify({'success': False, 'message': '請輸入搜尋關鍵字'})
        
        from creator_tracker import CreatorTracker
        tracker = CreatorTracker()
        
        results = tracker.search_creators(query, creator_type)
        
        return jsonify({
            'success': True,
            'results': results
        })
        
    except Exception as e:
        logger.error(f"搜尋設計師失敗: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/creator/<int:creator_id>/<creator_type>')
def creator_details_page(creator_id, creator_type):
    """設計師/繪師詳細資料頁面"""
    return render_template('creator_details.html', creator_id=creator_id, creator_type=creator_type)

@app.route('/api/creators/<int:creator_id>/<creator_type>')
def api_get_creator_details(creator_id, creator_type):
    """獲取設計師/繪師詳細資料 API"""
    try:
        from creator_tracker import CreatorTracker
        tracker = CreatorTracker()
        
        # 獲取詳細資料
        details = tracker.get_creator_details(creator_id, creator_type)
        if not details:
            return jsonify({'success': False, 'message': '無法獲取詳細資料'})
        
        # 確定正確的 API 類型
        api_type = 'boardgamedesigner' if creator_type in ['designer', 'boardgamedesigner'] else 'boardgameartist'
        slug = details.get('slug')
        
        # 獲取 average 排序的第一筆遊戲（top game）
        top_game = None
        if slug:
            top_games = tracker.get_all_creator_games(creator_id, slug, api_type, sort='average', limit=1)
            if top_games:
                game = top_games[0]
                top_game = {
                    'name': game.get('name'),
                    'url': f"https://boardgamegeek.com/boardgame/{game.get('bgg_id')}"
                }
        
        # 獲取 yearpublished 排序的前5筆遊戲
        recent_games = []
        if slug:
            games = tracker.get_all_creator_games(creator_id, slug, api_type, sort='yearpublished', limit=5)
            for game in games:
                recent_games.append({
                    'name': game.get('name'),
                    'year': game.get('year'),
                    'url': f"https://boardgamegeek.com/boardgame/{game.get('bgg_id')}"
                })
        
        # 檢查用戶是否已追蹤
        user_data = session.get('user')
        is_following = False
        
        if user_data and user_data.get('id'):
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT 1 FROM user_follows uf
                    JOIN creators c ON uf.creator_id = c.id
                    WHERE c.bgg_id = %s AND uf.user_id = %s
                """, (creator_id, user_data['id']))
                is_following = cursor.fetchone() is not None
        
        details['is_following'] = is_following
        details['top_game'] = top_game
        details['recent_games'] = recent_games
        
        return jsonify({
            'success': True,
            'creator': details
        })
        
    except Exception as e:
        logger.error(f"獲取設計師詳細資料失敗: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/creators/follow', methods=['POST'])
@full_access_required
def api_follow_creator():
    """追蹤/取消追蹤設計師/繪師 API"""
    try:
        user_data = session.get('user', {})
        user_id = user_data.get('id')
        user_email = user_data.get('email')
        
        if not user_id:
            return jsonify({'success': False, 'message': '請先登入'})
        
        data = request.get_json()
        creator_bgg_id = data.get('creator_id')
        creator_type = data.get('type')
        action = data.get('action')  # 'follow' or 'unfollow'
        
        if not all([creator_bgg_id, creator_type, action]):
            return jsonify({'success': False, 'message': '參數不完整'})
        
        # 檢查用戶是否設定了 email（追蹤功能需要 email 通知）
        if action == 'follow' and not user_email:
            return jsonify({'success': False, 'message': '請先在設定頁面設定 Email 地址才能使用追蹤功能'})
        
        from creator_tracker import CreatorTracker
        tracker = CreatorTracker()
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            config = get_database_config()
            
            if action == 'follow':
                # 1. 獲取並儲存設計師詳細資料
                details = tracker.get_creator_details(creator_bgg_id, creator_type)
                if not details:
                    return jsonify({'success': False, 'message': '無法獲取設計師資料'})
                
                # 2. 儲存設計師到資料庫
                creator_id = tracker.save_creator_to_db(details)
                if not creator_id:
                    return jsonify({'success': False, 'message': '儲存設計師資料失敗'})
                
                # 3. 檢查是否已存在此設計師的遊戲，並進行增量更新
                cursor.execute("""
                    SELECT bgg_game_id FROM creator_games WHERE creator_id = %s
                """, (creator_id,))
                existing_game_ids = [row[0] for row in cursor.fetchall()]
                
                # 獲取所有作品（用於新追蹤的設計師）或新作品（用於已存在的設計師）
                api_type = creator_type  # 前端已經傳遞正確的 API 類型
                
                if existing_game_ids:
                    # 已存在設計師，進行增量更新檢查新遊戲
                    new_games = tracker.get_creator_games_paginated(
                        creator_bgg_id, details['slug'], api_type, 
                        details['name'], existing_games=existing_game_ids,
                        stop_on_existing=True
                    )
                    if new_games:
                        tracker.save_creator_games(creator_id, new_games)
                        message = f'開始追蹤 {details["name"]}，發現 {len(new_games)} 個新作品'
                    else:
                        message = f'開始追蹤 {details["name"]}'
                else:
                    # 新設計師，獲取所有作品
                    all_games = tracker.get_all_creator_games(
                        creator_bgg_id, details['slug'], api_type
                    )
                    tracker.save_creator_games(creator_id, all_games)
                    message = f'開始追蹤 {details["name"]}，已記錄 {len(all_games)} 個作品'
                
                # 4. 建立追蹤關係
                now = datetime.now().isoformat()
                cursor.execute("""
                    INSERT INTO user_follows (user_id, creator_id, followed_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_id, creator_id) DO NOTHING
                """, (user_id, creator_id, now))
                
            else:  # unfollow
                # 取消追蹤
                cursor.execute("""
                    DELETE FROM user_follows 
                    WHERE user_id = %s AND creator_id = (
                        SELECT id FROM creators WHERE bgg_id = %s
                    )
                """, (user_id, creator_bgg_id))
                
                message = '已取消追蹤'
            
            # 提交數據庫事務
            conn.commit()
        
        return jsonify({
            'success': True,
            'message': message
        })
        
    except Exception as e:
        logger.error(f"追蹤操作失敗: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/recommendations/by-games', methods=['POST'])
@full_access_required
def api_get_recommendations_by_games():
    """根據用戶選擇的遊戲獲得推薦 API"""
    try:
        data = request.get_json()
        selected_games = data.get('games', [])
        num_recommendations = data.get('num_recommendations', 10)
        
        if not selected_games:
            return jsonify({'success': False, 'message': '請選擇至少一款遊戲'})
        
        if len(selected_games) > 10:
            return jsonify({'success': False, 'message': '最多只能選擇10款遊戲'})
        
        from game_recommendation_service import GameRecommendationService
        service = GameRecommendationService()
        
        result = service.get_game_recommendations_by_selection(selected_games, num_recommendations)
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"獲取遊戲推薦失敗: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/games/search', methods=['POST'])
def api_search_games():
    """搜尋遊戲 API（用於推薦系統的遊戲選擇）"""
    try:
        data = request.get_json()
        query = data.get('query', '').strip()
        limit = min(data.get('limit', 20), 50)  # 最多返回50個結果
        
        if not query:
            return jsonify({'success': False, 'message': '請輸入搜尋關鍵字'})
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT objectid, name, year, rating, rank, image, 
                       categories, mechanics
                FROM game_detail 
                WHERE name ILIKE %s 
                    AND rating IS NOT NULL 
                    AND rating > 5.0
                ORDER BY rating DESC, rank ASC
                LIMIT %s
            """, (f'%{query}%', limit))
            
            results = cursor.fetchall()
            games = []
            
            for row in results:
                games.append({
                    'objectid': row[0],
                    'name': row[1],
                    'year': row[2],
                    'rating': row[3],
                    'rank': row[4],
                    'image': row[5],
                    'categories': row[6],
                    'mechanics': row[7],
                    'display_name': f"{row[1]} ({row[2]})" if row[2] else row[1]
                })
            
            return jsonify({
                'success': True,
                'games': games,
                'query': query,
                'total': len(games)
            })
            
    except Exception as e:
        logger.error(f"搜尋遊戲失敗: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/recommendations')
def recommendations_page():
    """遊戲推薦頁面"""
    return render_template('recommendations.html')

@app.route('/api/creators/following')
@full_access_required
def api_get_following_creators():
    """獲取用戶追蹤的設計師/繪師列表 API"""
    try:
        user = session.get('user', {})
        user_id = user.get('id')
        if not user_id:
            return jsonify({'success': False, 'message': '請先登入'})
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            config = get_database_config()
            
            if config['type'] == 'postgresql':
                cursor.execute("""
                    SELECT c.bgg_id, c.name, c.type, c.description, c.image_url, uf.followed_at
                    FROM creators c
                    JOIN user_follows uf ON c.id = uf.creator_id
                    WHERE uf.user_id = %s
                    ORDER BY uf.followed_at DESC
                """, (user_id,))
            else:
                cursor.execute("""
                    SELECT c.bgg_id, c.name, c.type, c.description, c.image_url, uf.followed_at
                    FROM creators c
                    JOIN user_follows uf ON c.id = uf.creator_id
                    WHERE uf.user_id = ?
                    ORDER BY uf.followed_at DESC
                """, (user_id,))
            
            creators = []
            for row in cursor.fetchall():
                creators.append({
                    'bgg_id': row[0],
                    'name': row[1],
                    'type': row[2],
                    'description': row[3],
                    'image_url': row[4],
                    'followed_at': row[5]
                })
        
        return jsonify({
            'success': True,
            'creators': creators
        })
        
    except Exception as e:
        logger.error(f"獲取追蹤列表失敗: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/cron-update-creators', methods=['POST'])
def cron_update_creators():
    """定時更新設計師/繪師作品的 API 端點"""
    # 檢查授權
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({'success': False, 'message': '未授權'}), 401
    
    token = auth_header.split(' ')[1]
    expected_token = os.getenv('CRON_SECRET_TOKEN')
    
    if not expected_token or token != expected_token:
        return jsonify({'success': False, 'message': '授權失敗'}), 401
    
    try:
        data = request.get_json() or {}
        force_update = data.get('force', False)
        
        logger.info(f"開始更新設計師/繪師作品 (force: {force_update})")
        
        # 在背景執行更新程序
        import subprocess
        import threading
        
        def run_update():
            try:
                cmd = ['python3', 'update_creators.py']
                if force_update:
                    cmd.append('--force')
                
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=3600  # 1小時超時
                )
                
                if result.returncode == 0:
                    logger.info("設計師/繪師作品更新完成")
                else:
                    logger.error(f"設計師/繪師作品更新失敗: {result.stderr}")
                    
            except Exception as e:
                logger.error(f"執行更新腳本失敗: {e}")
        
        # 在背景執行
        update_thread = threading.Thread(target=run_update)
        update_thread.daemon = True
        update_thread.start()
        
        return jsonify({
            'success': True,
            'message': '設計師/繪師作品更新已開始',
            'force': force_update,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"觸發設計師更新失敗: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/save-user-email', methods=['POST'])
def api_save_user_email():
    """儲存用戶 Email API"""
    try:
        if 'logged_in' not in session:
            return jsonify({'success': False, 'message': '請先登入'}), 401
        
        data = request.get_json()
        email = data.get('email', '').strip()
        
        if not email:
            return jsonify({'success': False, 'message': '請輸入 Email 地址'})
        
        # 簡單的 email 格式驗證
        import re
        email_regex = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'
        if not re.match(email_regex, email):
            return jsonify({'success': False, 'message': '請輸入有效的 Email 地址'})
        
        # 更新 session 中的 email
        session['user_email'] = email
        
        # 如果有用戶系統，也可以儲存到資料庫
        # 這裡暫時只儲存在 session 中
        
        return jsonify({
            'success': True,
            'message': 'Email 地址已儲存'
        })
        
    except Exception as e:
        logger.error(f"儲存用戶 Email 失敗: {e}")
        return jsonify({'success': False, 'message': str(e)})

# ============================
# Email 認證路由
# ============================

@app.route('/register')
def register():
    """註冊頁面"""
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return render_template('register.html')

@app.route('/forgot-password')
def forgot_password():
    """忘記密碼頁面"""
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return render_template('forgot_password.html')

@app.route('/auth/send-code', methods=['POST'])
def send_verification_code():
    """發送驗證碼"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        code_type = data.get('type', 'register')
        
        if not email:
            return jsonify({'success': False, 'message': '請提供 Email 地址'})
        
        # 檢查 email 格式
        import re
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            return jsonify({'success': False, 'message': 'Email 格式無效'})
        
        # 對於登入和密碼重設，檢查用戶是否存在
        if code_type in ['login', 'password_reset']:
            user = email_auth.get_user_by_email(email)
            if not user:
                return jsonify({'success': False, 'message': '用戶不存在'})
            if not user['is_active']:
                return jsonify({'success': False, 'message': '帳號已被停用'})
        
        # 對於註冊，檢查用戶是否已存在
        elif code_type == 'register':
            user = email_auth.get_user_by_email(email)
            if user:
                return jsonify({'success': False, 'message': '此 Email 已註冊'})
        
        # 生成並發送驗證碼
        code = email_auth.generate_verification_code()
        
        # 儲存驗證碼
        if not email_auth.store_verification_code(email, code, code_type):
            return jsonify({'success': False, 'message': '驗證碼儲存失敗'})
        
        # 發送郵件
        if email_auth.send_verification_code(email, code, code_type):
            return jsonify({'success': True, 'message': '驗證碼已發送'})
        else:
            return jsonify({'success': False, 'message': '郵件發送失敗，請檢查 SMTP 設定'})
        
    except Exception as e:
        logger.error(f"發送驗證碼失敗: {e}")
        return jsonify({'success': False, 'message': f'系統錯誤: {str(e)}'})

@app.route('/auth/verify-code', methods=['POST'])
def verify_code():
    """驗證驗證碼"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        code = data.get('code', '').strip()
        code_type = data.get('type', 'register')
        
        if not email or not code:
            return jsonify({'success': False, 'message': '請提供 Email 和驗證碼'})
        
        # 驗證驗證碼
        if email_auth.verify_code(email, code, code_type):
            return jsonify({'success': True, 'message': '驗證成功'})
        else:
            return jsonify({'success': False, 'message': '驗證碼無效或已過期'})
        
    except Exception as e:
        logger.error(f"驗證驗證碼失敗: {e}")
        return jsonify({'success': False, 'message': f'系統錯誤: {str(e)}'})

@app.route('/auth/register', methods=['POST'])
def register_user():
    """完成用戶註冊"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        
        if not email or not password:
            return jsonify({'success': False, 'message': '請提供 Email 和密碼'})
        
        if len(password) < 6:
            return jsonify({'success': False, 'message': '密碼至少需要6個字符'})
        
        # 檢查是否有有效的驗證碼（確保用戶已通過驗證）
        with get_db_connection() as conn:
            cursor = conn.cursor()
            execute_query(cursor, """
                SELECT id FROM verification_codes 
                WHERE email = ? AND type = 'register' AND used = 1
                AND expires_at > ?
            """, (email, datetime.now().isoformat()))
            
            if not cursor.fetchone():
                return jsonify({'success': False, 'message': '請先完成 Email 驗證'})
        
        # 使用 email 前綴作為預設名稱
        name = email.split('@')[0]
        
        # 創建用戶
        user_data, message = email_auth.create_user(email, password, name)
        
        if user_data:
            # 設定 session
            session['user'] = user_data
            session['logged_in'] = True
            session['user_email'] = email
            
            # 清理已使用的驗證碼
            with get_db_connection() as conn:
                cursor = conn.cursor()
                execute_query(cursor, 
                    "DELETE FROM verification_codes WHERE email = ? AND type = 'register'", 
                    (email,))
                conn.commit()
            
            return jsonify({
                'success': True, 
                'message': message,
                'redirect': url_for('dashboard')
            })
        else:
            return jsonify({'success': False, 'message': message})
        
    except Exception as e:
        logger.error(f"用戶註冊失敗: {e}")
        return jsonify({'success': False, 'message': f'註冊失敗: {str(e)}'})

@app.route('/auth/login', methods=['POST'])
def login_user():
    """用戶登入"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        
        if not email or not password:
            return jsonify({'success': False, 'message': '請提供 Email 和密碼'})
        
        # 驗證用戶
        user_data, message = email_auth.authenticate_user(email, password)
        
        if user_data:
            # 設定 session
            session['user'] = user_data
            session['logged_in'] = True
            session['user_email'] = email
            return jsonify({
                'success': True,
                'message': message,
                'redirect': url_for('dashboard')
            })
        else:
            return jsonify({'success': False, 'message': message})
        
    except Exception as e:
        logger.error(f"用戶登入失敗: {e}")
        return jsonify({'success': False, 'message': f'登入失敗: {str(e)}'})

@app.route('/auth/verify-login', methods=['POST'])
def verify_login():
    """驗證碼登入"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        code = data.get('code', '').strip()
        
        if not email or not code:
            return jsonify({'success': False, 'message': '請提供 Email 和驗證碼'})
        
        # 檢查用戶是否存在
        user_data = email_auth.get_user_by_email(email)
        if not user_data:
            return jsonify({'success': False, 'message': '用戶不存在'})
        
        if not user_data['is_active']:
            return jsonify({'success': False, 'message': '帳號已被停用'})
        
        # 驗證驗證碼
        if email_auth.verify_code(email, code, 'login'):
            # 設定 session
            session['user'] = user_data
            session['logged_in'] = True
            session['user_email'] = email
            return jsonify({
                'success': True,
                'message': '登入成功',
                'redirect': url_for('dashboard')
            })
        else:
            return jsonify({'success': False, 'message': '驗證碼無效或已過期'})
        
    except Exception as e:
        logger.error(f"驗證碼登入失敗: {e}")
        return jsonify({'success': False, 'message': f'登入失敗: {str(e)}'})

@app.route('/auth/reset-password', methods=['POST'])
def reset_password():
    """重設密碼"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        code = data.get('code', '').strip()
        new_password = data.get('password', '')
        
        if not email or not code or not new_password:
            return jsonify({'success': False, 'message': '請提供完整資訊'})
        
        if len(new_password) < 6:
            return jsonify({'success': False, 'message': '密碼至少需要6個字符'})
        
        # 再次驗證驗證碼
        if not email_auth.verify_code(email, code, 'password_reset'):
            return jsonify({'success': False, 'message': '驗證碼無效或已過期'})
        
        # 更新密碼
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                from database import execute_query
                
                password_hash = email_auth.hash_password(new_password)
                updated_at = datetime.now().isoformat()
                
                execute_query(cursor, """
                    UPDATE users 
                    SET password_hash = ?, updated_at = ?
                    WHERE email = ?
                """, (password_hash, updated_at, email))
                
                conn.commit()
                
                return jsonify({'success': True, 'message': '密碼重設成功'})
                
        except Exception as e:
            logger.error(f"更新密碼失敗: {e}")
            return jsonify({'success': False, 'message': '密碼更新失敗'})
        
    except Exception as e:
        logger.error(f"重設密碼失敗: {e}")
        return jsonify({'success': False, 'message': f'重設失敗: {str(e)}'})

@app.route('/logout')
def logout():
    """登出"""
    session.clear()
    return redirect(url_for('login'))

# 模塊級資料庫初始化 - 適用於 Gunicorn/WSGI 環境
try:
    # 檢查是否應跳過模組級初始化（由 start_simple.py 設置）
    if not os.getenv('SKIP_MODULE_DB_INIT') and os.getenv('DATABASE_URL'):
        print("📋 模塊載入: 檢查資料庫初始化需求...")
        # 延遲執行，避免導入循環
        import threading
        def delayed_init():
            import time
            time.sleep(1)  # 等待 1 秒確保所有模塊載入完成
            force_db_initialization()
        
        init_thread = threading.Thread(target=delayed_init, daemon=True)
        init_thread.start()
        print("📋 模塊載入: 資料庫初始化線程已啟動")
    elif os.getenv('SKIP_MODULE_DB_INIT'):
        print("📋 模塊載入: 跳過資料庫初始化（由啟動腳本管理）")
except Exception as e:
    print(f"⚠️ 模塊級初始化警告: {e}")

if __name__ == '__main__':
    # 確保資料庫在應用啟動前完成初始化
    print("🔄 應用啟動前執行資料庫檢查...")
    force_db_initialization()
    
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)