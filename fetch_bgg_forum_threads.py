#!/usr/bin/env python3
import requests
import re
import os
from datetime import datetime, timedelta
import json
import xml.etree.ElementTree as ET
import openai
from dotenv import load_dotenv
import time
import argparse
from database import get_db_connection, get_database_config, init_database

# 數據庫初始化由 scheduler.py 負責，這裡不需要重複調用以避免並發問題
print("🗃️ [FETCH_BGG_FORUM_THREADS] 跳過數據庫初始化（由 scheduler.py 負責）")
print(f"🗃️ [FETCH_BGG_FORUM_THREADS] 當前時間: {datetime.utcnow().strftime('%H:%M:%S')}")
print("🗃️ [FETCH_BGG_FORUM_THREADS] 開始主要處理...")

# 設定日誌
import logging
logging.basicConfig(level=logging.INFO)

# 參考 comment_summarize_llm.py，載入 .env
load_dotenv()
OUTPUT_DIR = "outputs/forum_threads"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 解析參數
parser = argparse.ArgumentParser()
parser.add_argument('--lang', choices=['zh-tw', 'en'], default='zh-tw', help='推論語言')
args = parser.parse_args()
lang = args.lang

PROMPT_HEADER = {
    'zh-tw': "你是一位桌遊分析師，請根據下列討論串內容，推論該遊戲近期上榜的可能原因。可參考的常見原因有：1. 新遊戲且有潛力 2. 新版本 3. 公司倒閉 4. 出貨 5. 各種爭議(美術、抄襲、公關問題等等)\n請用繁體中文簡潔、專業地以一段流暢敘述，直接說明最關鍵的上榜原因，避免條列式、避免贅詞與開場白。",
    'en': "You are a board game analyst. Based on the following forum threads, infer the most likely reason why this game recently became hot. Common reasons include: 1. New and promising game 2. New edition 3. Publisher bankruptcy 4. Shipping 5. Controversies (art, plagiarism, PR, etc.)\nPlease write a concise, professional, and fluent English paragraph directly stating the key reason for the ranking. Avoid bullet points, filler, and introductions."
}

# 設定 requests 重試機制
session = requests.Session()
session.headers.update({'User-Agent': 'BGG Forum Threads Fetcher 1.0'})

def fetch_forum_list(objectid):
    """抓取遊戲的討論區列表"""
    try:
        url = f"https://boardgamegeek.com/xmlapi2/forumlist?id={objectid}&type=thing"
        response = session.get(url, timeout=10)
        if response.status_code != 200:
            print(f"⚠️ 無法取得討論區列表 objectid={objectid}, status={response.status_code}")
            return []

        root = ET.fromstring(response.content)
        forums = []
        for forum in root.findall('.//forum'):
            forum_id = forum.get('id')
            title = forum.get('title', '')
            if forum_id and title:
                forums.append({'id': forum_id, 'title': title})
        return forums
    except Exception as e:
        print(f"⚠️ 抓取討論區列表失敗 objectid={objectid}: {e}")
        return []

def fetch_forum_threads(forum_id, max_threads=5):
    """抓取討論區的討論串列表"""
    try:
        url = f"https://boardgamegeek.com/xmlapi2/forum?id={forum_id}"
        response = session.get(url, timeout=10)
        if response.status_code != 200:
            print(f"⚠️ 無法取得討論串列表 forum_id={forum_id}, status={response.status_code}")
            return []

        root = ET.fromstring(response.content)
        threads = []
        for thread in root.findall('.//thread')[:max_threads]:
            thread_id = thread.get('id')
            subject = thread.get('subject', '')
            lastpostdate = thread.get('lastpostdate', '')
            if thread_id and subject:
                threads.append({
                    'id': thread_id,
                    'subject': subject,
                    'lastpostdate': lastpostdate
                })
        return threads
    except Exception as e:
        print(f"⚠️ 抓取討論串列表失敗 forum_id={forum_id}: {e}")
        return []

def fetch_thread_posts(thread_id, max_posts=3):
    """抓取討論串的文章內容"""
    try:
        url = f"https://boardgamegeek.com/xmlapi2/thread?id={thread_id}&count={max_posts}"
        response = session.get(url, timeout=10)
        if response.status_code != 200:
            print(f"⚠️ 無法取得討論串內容 thread_id={thread_id}, status={response.status_code}")
            return []

        root = ET.fromstring(response.content)
        posts = []
        for article in root.findall('.//article'):
            username = article.get('username', '')
            postdate = article.get('postdate', '')
            body_elem = article.find('body')
            body = body_elem.text if body_elem is not None else ''

            # 清理 HTML 標籤
            if body:
                body = re.sub(r'<[^>]+>', '', body)
                body = body.strip()[:200]  # 限制長度

            if username and body:
                posts.append({
                    'author': username,
                    'postdate': postdate,
                    'body': body
                })
        return posts
    except Exception as e:
        print(f"⚠️ 抓取討論串內容失敗 thread_id={thread_id}: {e}")
        return []

# 查詢 i18n 是否已有翻譯且未過期
def is_i18n_fresh(objectid, lang, days=7):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        config = get_database_config()

        if config['type'] == 'postgresql':
            cursor.execute("SELECT updated_at FROM forum_threads_i18n WHERE objectid = %s AND lang = %s", (objectid, lang))
        else:
            cursor.execute("SELECT updated_at FROM forum_threads_i18n WHERE objectid = ? AND lang = ?", (objectid, lang))

        row = cursor.fetchone()
        if row and row[0]:
            try:
                dt = datetime.fromisoformat(row[0])
                if datetime.utcnow() - dt < timedelta(days=days):
                    return True
            except Exception:
                pass
        return False

def summarize_reason_with_llm(game_name, threads):
    """使用 LLM 分析討論串並產生上榜原因"""
    print(f"🤖 開始為 {game_name} 分析討論串...")

    # 若沒有討論串，產生預設回應
    if not threads:
        print(f"⚠️ {game_name} 沒有討論串資料")
        if lang == 'zh-tw':
            return f"因為討論資料過少，無法推論 {game_name} 的上榜原因。"
        else:
            return f"Unable to infer the reason for {game_name}'s popularity due to insufficient discussion data."

    # 檢查討論串內容是否過少（例如：討論串數量少於2個，或總留言數少於3個）
    total_posts = sum(len(t.get('posts', [])) for t in threads)
    print(f"📊 {game_name}: {len(threads)} 個討論串，共 {total_posts} 個留言")

    if len(threads) < 2 or total_posts < 3:
        print(f"⚠️ {game_name} 討論資料過少（討論串: {len(threads)}, 留言: {total_posts}）")
        if lang == 'zh-tw':
            return f"因為討論資料過少，無法推論 {game_name} 的上榜原因。"
        else:
            return f"Unable to infer the reason for {game_name}'s popularity due to insufficient discussion data."

    # 若 lang == 'en' 且 threads 全為英文，直接組合 reason
    if lang == 'en' and threads and all(is_english_thread(t) for t in threads):
        print(f"🔤 {game_name} 為英文討論串，直接組合原因...")
        # 直接用第一個討論串標題與前幾則留言組合一段英文 reason
        reason = f"Key discussion for {game_name}: "
        for t in threads[:1]:
            reason += f"{t['title']}. "
            for p in t['posts'][:2]:
                reason += f"{p['author']}: {p['body'][:80]}. "
        print(f"✅ {game_name} 英文原因組合完成")
        return reason.strip()

    # 否則呼叫 LLM
    print(f"🤖 準備調用 OpenAI API 分析 {game_name}...")
    print(f"🎯 遊戲名稱: {game_name}")
    print(f"🌐 目標語言: {lang}")
    print(f"📊 討論串數量: {len(threads)}")

    prompt = PROMPT_HEADER[lang] + f"\n\nGame: {game_name}\nForum thread summary:\n"
    for t in threads:
        prompt += f"\n- {t['title']} ({t['postdate']})"
        for p in t['posts'][:2]:
            prompt += f"\n  - {p['author']}：{p['body'][:80]}"

    print(f"📝 Prompt 長度: {len(prompt)} 字符")
    print(f"🔧 模型: {os.getenv('OPENAI_MODEL', 'gpt-3.5-turbo')}")

    # 重試機制
    max_retries = 3
    for attempt in range(max_retries):
        try:
            print(f"🔄 [{game_name}] 第 {attempt + 1}/{max_retries} 次嘗試調用 OpenAI API...")

            client = openai.OpenAI(
                api_key=os.getenv("OPENAI_API_KEY"),
                timeout=60.0  # 設置 60 秒超時
            )

            print(f"⏰ [{game_name}] 開始 API 調用... (超時: 60秒)")
            start_time = time.time()

            response = client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-3.5-turbo"),
                messages=[{"role": "user", "content": prompt}],
                max_tokens=512,
                temperature=0.5,
                timeout=60.0  # 額外的超時設置
            )

            end_time = time.time()
            duration = end_time - start_time
            print(f"✅ [{game_name}] API 調用成功！耗時: {duration:.2f} 秒")

            reason = response.choices[0].message.content.strip()
            print(f"📝 [{game_name}] 分析結果: {reason[:100]}...")
            print(f"🎉 [{game_name}] LLM 分析完成！")
            return reason

        except openai.APITimeoutError as timeout_error:
            print(f"⏰ [{game_name}] 第 {attempt + 1} 次嘗試 - API 超時: {timeout_error}")
            if attempt == max_retries - 1:
                print(f"❌ [{game_name}] 所有重試都超時，返回預設訊息")
                if lang == 'zh-tw':
                    return f"由於 API 超時，無法分析 {game_name} 的上榜原因。"
                else:
                    return f"Unable to analyze {game_name} due to API timeout."
            print(f"⏳ [{game_name}] 等待 {2 ** attempt} 秒後重試...")
            time.sleep(2 ** attempt)  # 指數退避

        except openai.RateLimitError as rate_error:
            print(f"🚫 [{game_name}] 第 {attempt + 1} 次嘗試 - API 速率限制: {rate_error}")
            if attempt == max_retries - 1:
                print(f"❌ [{game_name}] 所有重試都遇到速率限制，返回預設訊息")
                if lang == 'zh-tw':
                    return f"由於 API 速率限制，無法分析 {game_name} 的上榜原因。"
                else:
                    return f"Unable to analyze {game_name} due to API rate limit."
            wait_time = 5 * (attempt + 1)
            print(f"⏳ [{game_name}] 等待 {wait_time} 秒後重試...")
            time.sleep(wait_time)

        except Exception as e:
            print(f"❌ [{game_name}] 第 {attempt + 1} 次嘗試失敗: {e}")
            if attempt == max_retries - 1:
                print(f"❌ [{game_name}] 所有重試都失敗，返回預設訊息")
                if lang == 'zh-tw':
                    return f"由於技術問題，無法分析 {game_name} 的上榜原因。"
                else:
                    return f"Unable to analyze {game_name} due to technical issues."
            print(f"⏳ [{game_name}] 等待 {2 * (attempt + 1)} 秒後重試...")
            time.sleep(2 * (attempt + 1))

    # 所有重試都失敗了
    print(f"❌ {game_name} 的 LLM 分析完全失敗，使用預設回應")
    if lang == 'zh-tw':
        reason = f"因為 API 調用失敗，無法推論 {game_name} 的上榜原因。"
    else:
        reason = f"Unable to infer the reason for {game_name}'s popularity due to API failure."
    return reason

def is_english_thread(thread):
    # 判斷討論串標題與留言是否為英文（簡單判斷，遇到非英文字母比例過高則視為非英文）
    import string
    def is_english(text):
        letters = sum(1 for c in text if c in string.ascii_letters)
        return letters / max(1, len(text)) > 0.6
    if not is_english(thread['title']):
        return False
    for p in thread['posts']:
        if not is_english(p['body']):
            return False
    return True

def is_threads_expired(objectid):
    """檢查討論串是否過期（7天）"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        config = get_database_config()

        if config['type'] == 'postgresql':
            cursor.execute("SELECT MAX(created_at), threads_json FROM forum_threads WHERE objectid = %s ORDER BY created_at DESC LIMIT 1", (objectid,))
        else:
            cursor.execute("SELECT MAX(created_at), threads_json FROM forum_threads WHERE objectid = ? ORDER BY created_at DESC LIMIT 1", (objectid,))

        row = cursor.fetchone()
        if not row or not row[0]:
            return True

        # 檢查討論串內容是否為空
        try:
            threads_data = json.loads(row[1]) if row[1] else []
            if not threads_data:  # 如果討論串為空，也視為過期
                return True
        except Exception:
            return True

        # 檢查時間是否過期
        try:
            dt = datetime.fromisoformat(row[0])
            return (datetime.utcnow() - dt).days >= 7
        except Exception:
            return True

def delete_all_threads_and_i18n(objectid):
    """刪除指定遊戲的所有討論串和多語言推論"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        config = get_database_config()

        if config['type'] == 'postgresql':
            cursor.execute("DELETE FROM forum_threads_i18n WHERE objectid = %s", (objectid,))
            cursor.execute("DELETE FROM forum_threads WHERE objectid = %s", (objectid,))
        else:
            cursor.execute("DELETE FROM forum_threads_i18n WHERE objectid = ?", (objectid,))
            cursor.execute("DELETE FROM forum_threads WHERE objectid = ?", (objectid,))

        conn.commit()

def fetch_and_save_threads(objectid, name):
    """實際抓取並儲存討論串內容"""
    print(f"🔍 正在抓取 {name} ({objectid}) 的討論串...")

    # 1. 抓取討論區列表
    forums = fetch_forum_list(objectid)
    if not forums:
        print(f"⚠️ 無討論區資料 objectid={objectid}")
        threads = []
    else:
        threads = []
        # 2. 從前幾個討論區抓取討論串
        for forum in forums[:3]:  # 只抓前3個討論區
            time.sleep(0.3)  # 避免請求過快（優化：從1秒減少到0.3秒）
            forum_threads = fetch_forum_threads(forum['id'], max_threads=3)

            for thread_info in forum_threads:
                time.sleep(0.3)  # 避免請求過快（優化：從1秒減少到0.3秒）
                posts = fetch_thread_posts(thread_info['id'], max_posts=3)

                if posts:  # 只保留有內容的討論串
                    threads.append({
                        'title': thread_info['subject'],
                        'postdate': thread_info['lastpostdate'],
                        'posts': posts
                    })

                if len(threads) >= 5:  # 限制總討論串數量
                    break

            if len(threads) >= 5:
                break

    # 3. 儲存到資料庫
    with get_db_connection() as conn:
        cursor = conn.cursor()
        config = get_database_config()

        if config['type'] == 'postgresql':
            cursor.execute("""
                INSERT INTO forum_threads (objectid, name, threads_json, snapshot_date, created_at)
                VALUES (%s, %s, %s, %s, %s)
            """, (objectid, name, json.dumps(threads, ensure_ascii=False), datetime.utcnow().strftime("%Y-%m-%d"), datetime.utcnow().isoformat()))
        else:
            cursor.execute("""
                INSERT INTO forum_threads (objectid, name, threads_json, snapshot_date, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (objectid, name, json.dumps(threads, ensure_ascii=False), datetime.utcnow().strftime("%Y-%m-%d"), datetime.utcnow().isoformat()))

        conn.commit()

    print(f"✅ 已抓取 {len(threads)} 個討論串 objectid={objectid}")
    return threads

def get_threads_by_objectid(objectid):
    """根據 objectid 獲取討論串資料"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        config = get_database_config()

        if config['type'] == 'postgresql':
            cursor.execute("SELECT threads_json FROM forum_threads WHERE objectid = %s ORDER BY created_at DESC LIMIT 1", (objectid,))
        else:
            cursor.execute("SELECT threads_json FROM forum_threads WHERE objectid = ? ORDER BY created_at DESC LIMIT 1", (objectid,))

        row = cursor.fetchone()
        if row:
            return json.loads(row[0])
        return []

def is_threads_expired_with_cursor(cursor, objectid, config):
    if config['type'] == 'postgresql':
        cursor.execute("SELECT MAX(created_at), threads_json FROM forum_threads WHERE objectid = %s ORDER BY created_at DESC LIMIT 1", (objectid,))
    else:
        cursor.execute("SELECT MAX(created_at), threads_json FROM forum_threads WHERE objectid = ? ORDER BY created_at DESC LIMIT 1", (objectid,))
    row = cursor.fetchone()
    if not row or not row[0]:
        return True

    # 檢查討論串內容是否為空
    try:
        threads_data = json.loads(row[1]) if row[1] else []
        if not threads_data:  # 如果討論串為空，也視為過期
            return True
    except Exception:
        return True

    # 檢查時間是否過期
    try:
        dt = datetime.fromisoformat(row[0])
        return (datetime.utcnow() - dt).days >= 7
    except Exception:
        return True

def delete_all_threads_and_i18n_with_cursor(cursor, conn, objectid, config):
    if config['type'] == 'postgresql':
        cursor.execute("DELETE FROM forum_threads_i18n WHERE objectid = %s", (objectid,))
        cursor.execute("DELETE FROM forum_threads WHERE objectid = %s", (objectid,))
    else:
        cursor.execute("DELETE FROM forum_threads_i18n WHERE objectid = ?", (objectid,))
        cursor.execute("DELETE FROM forum_threads WHERE objectid = ?", (objectid,))
    conn.commit()

def fetch_and_save_threads_with_cursor(cursor, conn, objectid, name, config):
    """實際抓取並儲存討論串內容"""
    print(f"🔍 [{name}] 正在抓取討論串...")

    # 1. 抓取討論區列表
    print(f"📋 [{name}] 步驟1: 獲取討論區列表...")
    forums = fetch_forum_list(objectid)
    if not forums:
        print(f"⚠️ [{name}] 無討論區資料 objectid={objectid}")
        threads = []
    else:
        print(f"📋 [{name}] 找到 {len(forums)} 個討論區，將抓取前3個")
        threads = []
        # 2. 從前幾個討論區抓取討論串
        for i, forum in enumerate(forums[:3], 1):  # 只抓前3個討論區
            print(f"📋 [{name}] 正在處理討論區 {i}/3: {forum.get('name', forum['id'])}")
            time.sleep(0.3)  # 避免請求過快（優化：從1秒減少到0.3秒）
            forum_threads = fetch_forum_threads(forum['id'], max_threads=3)
            print(f"📄 [{name}] 討論區 {i} 找到 {len(forum_threads)} 個討論串")

            for j, thread_info in enumerate(forum_threads, 1):
                print(f"📄 [{name}] 處理討論串 {j}/{len(forum_threads)}: {thread_info['subject'][:40]}...")
                time.sleep(0.3)  # 避免請求過快（優化：從1秒減少到0.3秒）
                posts = fetch_thread_posts(thread_info['id'], max_posts=3)

                if posts:  # 只保留有內容的討論串
                    threads.append({
                        'title': thread_info['subject'],
                        'postdate': thread_info['lastpostdate'],
                        'posts': posts
                    })
                    print(f"✅ [{name}] 討論串已保存，共 {len(posts)} 個留言")

                if len(threads) >= 5:  # 限制總討論串數量
                    print(f"📄 [{name}] 已達到討論串上限 (5個)，停止抓取")
                    break

            if len(threads) >= 5:
                break

    # 3. 儲存到資料庫
    print(f"💾 [{name}] 保存討論串到數據庫...")
    if config['type'] == 'postgresql':
        cursor.execute("""
            INSERT INTO forum_threads (objectid, name, threads_json, snapshot_date, created_at)
            VALUES (%s, %s, %s, %s, %s)
        """, (objectid, name, json.dumps(threads, ensure_ascii=False), datetime.utcnow().strftime("%Y-%m-%d"), datetime.utcnow().isoformat()))
    else:
        cursor.execute("""
            INSERT INTO forum_threads (objectid, name, threads_json, snapshot_date, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (objectid, name, json.dumps(threads, ensure_ascii=False), datetime.utcnow().strftime("%Y-%m-%d"), datetime.utcnow().isoformat()))
    conn.commit()

    print(f"✅ [{name}] 已抓取 {len(threads)} 個討論串")
    return threads

def get_threads_by_objectid_with_cursor(cursor, objectid, config):
    if config['type'] == 'postgresql':
        cursor.execute("SELECT threads_json FROM forum_threads WHERE objectid = %s ORDER BY created_at DESC LIMIT 1", (objectid,))
    else:
        cursor.execute("SELECT threads_json FROM forum_threads WHERE objectid = ? ORDER BY created_at DESC LIMIT 1", (objectid,))
    row = cursor.fetchone()
    if row:
        return json.loads(row[0])
    return []

def main():
    today = datetime.utcnow().strftime("%Y-%m-%d")
    output_path = f"{OUTPUT_DIR}/forum_threads_{today}.json"
    # 檢查是否已有檔案且時間小於 7 天
    if os.path.exists(output_path):
        mtime = os.path.getmtime(output_path)
        if time.time() - mtime < 7 * 24 * 60 * 60:
            print(f"⏩ {output_path} 已存在且距今未滿 7 天，直接跳過。")
            return

    # 使用正確的資料庫連接
    with get_db_connection() as conn:
        cursor = conn.cursor()
        config = get_database_config()

        # 獲取需要處理的遊戲：新進榜 + 沒有討論串資料的遊戲
        def get_games_to_process():
            # 1. 新進榜的遊戲
            if config['type'] == 'postgresql':
                cursor.execute("SELECT DISTINCT snapshot_date FROM hot_games ORDER BY snapshot_date DESC LIMIT 2")
            else:
                cursor.execute("SELECT DISTINCT snapshot_date FROM hot_games ORDER BY snapshot_date DESC LIMIT 2")

            rows = cursor.fetchall()
            new_games = []
            if len(rows) >= 2:
                today_date, yesterday_date = rows[0][0], rows[1][0]

                if config['type'] == 'postgresql':
                    cursor.execute("SELECT objectid, name FROM hot_games WHERE snapshot_date = %s", (today_date,))
                else:
                    cursor.execute("SELECT objectid, name FROM hot_games WHERE snapshot_date = ?", (today_date,))
                today_list = cursor.fetchall()

                if config['type'] == 'postgresql':
                    cursor.execute("SELECT objectid FROM hot_games WHERE snapshot_date = %s", (yesterday_date,))
                else:
                    cursor.execute("SELECT objectid FROM hot_games WHERE snapshot_date = ?", (yesterday_date,))
                yesterday_ids = [r[0] for r in cursor.fetchall()]
                new_games = [(oid, name) for oid, name in today_list if oid not in yesterday_ids]

            # 2. 今日榜上但沒有討論串資料或翻譯的遊戲
            if config['type'] == 'postgresql':
                cursor.execute("""
                    SELECT h.objectid, h.name
                    FROM hot_games h
                    WHERE h.snapshot_date = (SELECT MAX(snapshot_date) FROM hot_games)
                    AND (
                        h.objectid NOT IN (SELECT DISTINCT objectid FROM forum_threads)
                        OR h.objectid NOT IN (SELECT DISTINCT objectid FROM forum_threads_i18n WHERE lang = %s)
                    )
                """, (lang,))
            else:
                cursor.execute("""
                    SELECT h.objectid, h.name
                    FROM hot_games h
                    WHERE h.snapshot_date = (SELECT MAX(snapshot_date) FROM hot_games)
                    AND (
                        h.objectid NOT IN (SELECT DISTINCT objectid FROM forum_threads)
                        OR h.objectid NOT IN (SELECT DISTINCT objectid FROM forum_threads_i18n WHERE lang = ?)
                    )
                """, (lang,))
            missing_games = cursor.fetchall()

            # 合併並去重
            all_games = {}
            for oid, name in new_games + missing_games:
                all_games[oid] = name

            return list(all_games.items())

        games_to_process = get_games_to_process()
        all_results = {}

        print(f"📊 找到 {len(games_to_process)} 個遊戲需要處理討論串")
        if len(games_to_process) == 0:
            print("✅ 沒有遊戲需要處理，任務完成")
            return

        print(f"\n🎯 開始批量處理 {len(games_to_process)} 款遊戲的討論串翻譯")
        print(f"🌐 目標語言: {lang}")
        print(f"📅 處理開始時間: {datetime.now().strftime('%H:%M:%S')}")
        print(f"⏱️ 預估總耗時: {len(games_to_process) * 30 / 60:.1f} 分鐘")
        print(f"🎮 遊戲列表:")
        for idx, (objectid, name) in enumerate(games_to_process[:10], 1):
            print(f"  {idx:2d}. {name} ({objectid})")
        if len(games_to_process) > 10:
            print(f"  ... 還有 {len(games_to_process) - 10} 款遊戲")
        print(f"{'='*80}")

        for i, (objectid, name) in enumerate(games_to_process, 1):
            start_time = time.time()
            print(f"\n{'='*80}")
            print(f"🎮 [{i}/{len(games_to_process)}] 📍 正在處理遊戲: {name}")
            print(f"🆔 ObjectID: {objectid}")
            print(f"🔧 目標語言: {lang}")
            print(f"📅 開始時間: {datetime.now().strftime('%H:%M:%S')}")
            print(f"⏱️ 預估完成時間: {datetime.now() + timedelta(seconds=(len(games_to_process) - i + 1) * 30)}")
            print(f"{'='*80}")

            try:
                # 1. 判斷討論串是否過期或不存在
                print(f"🔍 [步驟1/3] 檢查 {name} 的討論串是否需要更新...")
                if is_threads_expired_with_cursor(cursor, objectid, config):
                    print(f"⏩ {name} 討論串已過期或不存在，重抓並刪除所有語言 reason")
                    delete_all_threads_and_i18n_with_cursor(cursor, conn, objectid, config)
                    print(f"📥 [步驟2/3] 開始抓取 {name} 的新討論串...")
                    threads_start = time.time()
                    threads = fetch_and_save_threads_with_cursor(cursor, conn, objectid, name, config)
                    threads_time = time.time() - threads_start
                    print(f"📥 ✅ {name} 討論串抓取完成，共 {len(threads) if threads else 0} 個 (耗時: {threads_time:.1f}秒)")
                else:
                    print(f"✅ [步驟2/3] {name} 使用現有討論串資料")
                    threads = get_threads_by_objectid_with_cursor(cursor, objectid, config)

                # 2. 若該語言 reason 不存在，才丟給 LLM
                print(f"🔍 檢查 {name} 是否已有 {lang} 語言的分析結果...")
                if config['type'] == 'postgresql':
                    cursor.execute("SELECT 1 FROM forum_threads_i18n WHERE objectid = %s AND lang = %s", (objectid, lang))
                else:
                    cursor.execute("SELECT 1 FROM forum_threads_i18n WHERE objectid = ? AND lang = ?", (objectid, lang))
                reason_exists = cursor.fetchone() is not None

                if reason_exists:
                    print(f"⏩ ✅ {name} 已有新鮮 {lang} reason，跳過")
                    print(f"🎉 [{i}/{len(games_to_process)}] {name} 處理完成 (使用現有分析)")
                    continue

                # 3. 用現有 threads 產生 reason
                print(f"🤖 [步驟3/3] 開始為 {name} 產生 {lang} 語言分析...")
                print(f"📊 討論串資料: {len(threads) if threads else 0} 個討論串")

                if threads:
                    total_posts = sum(len(t.get('posts', [])) for t in threads)
                    print(f"📊 總留言數: {total_posts} 個")
                    print(f"🔍 討論串標題預覽:")
                    for idx, thread in enumerate(threads[:3], 1):
                        print(f"  {idx}. {thread.get('title', 'N/A')[:60]}...")

                llm_start = time.time()
                reason = summarize_reason_with_llm(name, threads)
                llm_time = time.time() - llm_start
                print(f"🤖 ✅ {name} LLM 分析完成！(耗時: {llm_time:.1f}秒)")
                print(f"📝 分析結果摘要: {reason[:120]}...")

                print(f"💾 保存 {name} 的分析結果到數據庫...")
                if config['type'] == 'postgresql':
                    cursor.execute("""
                        INSERT INTO forum_threads_i18n (objectid, lang, reason, updated_at)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT(objectid, lang) DO UPDATE SET reason=EXCLUDED.reason, updated_at=EXCLUDED.updated_at
                    """, (objectid, lang, reason, datetime.utcnow().isoformat()))
                else:
                    cursor.execute("""
                        INSERT INTO forum_threads_i18n (objectid, lang, reason, updated_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(objectid, lang) DO UPDATE SET reason=excluded.reason, updated_at=excluded.updated_at
                    """, (objectid, lang, reason, datetime.utcnow().isoformat()))

                all_results[objectid] = {
                    "name": name,
                    "threads": threads,
                    "reason": reason
                }

                end_time = time.time()
                duration = end_time - start_time
                avg_time = duration / i if i > 0 else duration
                remaining_games = len(games_to_process) - i
                estimated_remaining = remaining_games * avg_time

                print(f"🎉 ✅ [{i}/{len(games_to_process)}] {name} 完成處理！(總耗時: {duration:.1f}秒)")
                print(f"📊 進度統計: 平均每遊戲 {avg_time:.1f}秒, 預估剩餘 {int(estimated_remaining/60)}分{int(estimated_remaining%60)}秒")
                print(f"{'='*80}")

            except Exception as e:
                end_time = time.time()
                duration = end_time - start_time
                print(f"❌ ⚠️ [{i}/{len(games_to_process)}] 處理遊戲 {name} ({objectid}) 時發生錯誤!")
                print(f"❌ 錯誤訊息: {e}")
                import traceback
                print(f"❌ 錯誤詳情: {traceback.format_exc()}")
                print(f"⏱️ 錯誤發生時間: {duration:.1f}秒")
                print(f"{'='*80}")
                continue

        conn.commit()
        print(f"\n💾 數據庫提交完成")

    # 計算處理統計
    total_processed = len(all_results)
    total_games = len(games_to_process)
    success_rate = (total_processed / total_games * 100) if total_games > 0 else 0

    print(f"\n🎉 討論串翻譯任務完成！")
    print(f"{'='*80}")
    print(f"📊 處理統計:")
    print(f"  🎮 總遊戲數量: {total_games} 款")
    print(f"  ✅ 成功處理: {total_processed} 款 ({success_rate:.1f}%)")
    print(f"  ❌ 處理失敗: {total_games - total_processed} 款")
    print(f"  🌐 目標語言: {lang}")
    print(f"  📅 完成時間: {datetime.now().strftime('%H:%M:%S')}")

    if all_results:
        print(f"📝 成功處理的遊戲:")
        for idx, (objectid, data) in enumerate(list(all_results.items())[:5], 1):
            reason_preview = data['reason'][:80] + "..." if len(data['reason']) > 80 else data['reason']
            print(f"  {idx}. {data['name']}: {reason_preview}")
        if len(all_results) > 5:
            print(f"  ... 還有 {len(all_results) - 5} 款遊戲分析完成")

    print(f"{'='*80}")

    # 儲存 debug 檔案
    print(f"💾 儲存結果到 {output_path}")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"🎉 討論串處理完成，共處理 {len(all_results)} 個遊戲")

if __name__ == "__main__":
    main()