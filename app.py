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

            # 獲取遊戲基本資料
            cursor.execute("""
                SELECT rating, rank, weight, minplayers, maxplayers, bestplayers,
                       minplaytime, maxplaytime, image
                FROM game_detail
                WHERE objectid = ?
            """, (objectid,))

            game_detail = cursor.fetchone()

            # 獲取所有類型的分類資料
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

        # 組織返回資料
        if game_detail:
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
                'categories': categories['boardgamecategory'],
                'mechanics': categories['boardgamemechanic'],
                'designers': categories['boardgamedesigner'],
                'artists': categories['boardgameartist'],
                'publishers': categories['boardgamepublisher']
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

                        # 從資料庫獲取完整的遊戲詳細資料
                        db_details = get_game_details_from_db(game_objectid) if game_objectid else {}

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
                reason_match = re.search(r'\*\*📈 上榜原因推論：\*\*\s*>\s*([^-]+?)(?=\n---|####|\nz{3,}|\n##|\n###|$)', section_content, re.DOTALL)
                if reason_match:
                    reason_text = reason_match.group(1).strip()
                    # 清理多餘的空白和換行並移除前綴
                    reason_text = re.sub(r'\s+', ' ', reason_text)
                    # 移除《遊戲名》近期上榜的主要原因是 這類前綴
                    reason_text = re.sub(r'^《[^》]+》[^，。]*?[的是]', '', reason_text)
                    # 移除其他可能的前綴
                    reason_text = re.sub(r'^[^，。]*?主要原因是', '', reason_text)
                    reason_text = reason_text.strip()
                    game['reason'] = reason_text

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
            '--lang', 'zh-tw',
            '--force'
        ]
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

        while process.poll() is None:  # 進程還在運行
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

            # 短暫休眠，避免過度消耗 CPU
            time.sleep(1)

            # 更新進度（模擬進度更新）
            elapsed = (datetime.now() - task_status['start_time']).total_seconds()
            estimated_progress = min(10 + (elapsed / 1200) * 80, 90)  # 預估進度，最多到90%
            update_task_status('執行中', int(estimated_progress), f'正在執行數據抓取和報表生成... ({int(elapsed/60)} 分鐘)')

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

def generate_report():
    """產生新的報表"""
    try:
        logger.info("開始產生報表...")

        # 檢查是否已有任務在運行
        if task_status['is_running']:
            elapsed = (datetime.now() - task_status['start_time']).total_seconds() if task_status['start_time'] else 0
            return True, f"報表產生中... 已運行 {int(elapsed/60)} 分鐘，當前步驟: {task_status['current_step']}"

        # 重置任務狀態，清除之前的停止標誌
        reset_task_status()

        # 啟動異步任務
        thread = threading.Thread(target=run_scheduler_async)
        thread.daemon = True
        thread.start()

        return True, "報表產生任務已啟動，請稍後檢查進度"

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

    success, message = generate_report()
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

@app.route('/health')
def health():
    """健康檢查端點"""
    return {'status': 'ok', 'timestamp': datetime.now().isoformat()}

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)