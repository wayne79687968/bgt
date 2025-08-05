#!/usr/bin/env python3
import os
from datetime import datetime, date
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from dotenv import load_dotenv
import subprocess
import logging
import glob
import re
import json
from database import get_db_connection, get_database_config
import threading
import time

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

# 登入憑證
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'password')

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
                    placeholders = ','.join(['?' if config['type'] == 'sqlite' else '%s'] * len(reason_objectids))
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

@app.route('/')
def index():
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

    # 將 Markdown 轉換為 HTML（如果可用）
    if MARKDOWN_AVAILABLE:
        html_content = markdown.markdown(content, extensions=['tables', 'fenced_code'])
    else:
        # 如果沒有 markdown 模組，使用 <pre> 標籤顯示原始文字
        html_content = f"<pre>{content}</pre>"

    # 獲取所有可用日期
    available_dates = get_available_dates()

    return render_template('report.html',
                         content=html_content,
                         filename=filename,
                         selected_date=selected_date,
                         available_dates=available_dates,
                         last_updated=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

@app.route('/settings')
def settings():
    """設定頁面"""
    if 'logged_in' not in session:
        return redirect(url_for('login'))

    available_dates = get_available_dates()
    return render_template('settings.html', available_dates=available_dates)

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

@app.route('/api/schedule-settings', methods=['GET', 'POST'])
def api_schedule_settings():
    """API端點：排程設定"""
    if 'logged_in' not in session:
        return jsonify({'success': False, 'message': '未登入'}), 401

    schedule_file = 'schedule_settings.json'
    
    if request.method == 'GET':
        # 讀取現有設定
        try:
            if os.path.exists(schedule_file):
                with open(schedule_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                return jsonify({
                    'success': True,
                    'hour': settings.get('hour', 23),
                    'minute': settings.get('minute', 0)
                })
            else:
                # 預設值
                return jsonify({
                    'success': True,
                    'hour': 23,
                    'minute': 0
                })
        except Exception as e:
            logger.error(f"讀取排程設定失敗: {e}")
            return jsonify({'success': False, 'message': f'讀取設定失敗: {e}'})
    
    elif request.method == 'POST':
        # 儲存新設定
        try:
            data = request.get_json()
            hour = int(data.get('hour', 23))
            minute = int(data.get('minute', 0))
            
            # 驗證輸入
            if not (0 <= hour <= 23) or not (0 <= minute <= 59):
                return jsonify({'success': False, 'message': '時間格式不正確'})
            
            settings = {
                'hour': hour,
                'minute': minute,
                'updated_at': datetime.now().isoformat()
            }
            
            with open(schedule_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
            
            logger.info(f"排程設定已更新: {hour:02d}:{minute:02d}")
            
            return jsonify({
                'success': True,
                'message': f'排程時間已設定為 {hour:02d}:{minute:02d}'
            })
            
        except Exception as e:
            logger.error(f"儲存排程設定失敗: {e}")
            return jsonify({'success': False, 'message': f'儲存設定失敗: {e}'})

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['logged_in'] = True
            flash('登入成功！', 'success')
            return redirect(url_for('index'))
        else:
            flash('帳號或密碼錯誤！', 'error')

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    flash('已登出', 'info')
    return redirect(url_for('login'))

@app.route('/generate')
def generate():
    if 'logged_in' not in session:
        return redirect(url_for('login'))

    success, message = generate_report()
    if success:
        flash(message, 'success')
    else:
        flash(message, 'error')

    return redirect(url_for('index'))

@app.route('/newspaper')
def newspaper():
    """報紙風格的報表檢視"""
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

    # 解析所有遊戲資料 - 一次顯示全部
    all_games = parse_game_data_from_report(content)
    current_page_games = all_games  # 顯示所有遊戲
    total_games = len(all_games)

    # 獲取所有可用日期
    available_dates = get_available_dates()

    return render_template('newspaper.html',
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
            if config['type'] == 'postgresql':
                cursor.execute("""
                    SELECT table_name FROM information_schema.tables
                    WHERE table_schema = 'public'
                    ORDER BY table_name
                """)
            else:
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")

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
    """健康檢查端點"""
    return {'status': 'ok', 'timestamp': datetime.now().isoformat()}

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)