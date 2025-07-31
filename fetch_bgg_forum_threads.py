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
from database import get_db_connection, get_database_config

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

# DB 連線
conn = None
cursor = None

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
    # 若沒有討論串，產生預設回應
    if not threads:
        if lang == 'zh-tw':
            return f"因為討論資料過少，無法推論 {game_name} 的上榜原因。"
        else:
            return f"Unable to infer the reason for {game_name}'s popularity due to insufficient discussion data."

    # 檢查討論串內容是否過少（例如：討論串數量少於2個，或總留言數少於3個）
    total_posts = sum(len(t.get('posts', [])) for t in threads)
    if len(threads) < 2 or total_posts < 3:
        if lang == 'zh-tw':
            return f"因為討論資料過少，無法推論 {game_name} 的上榜原因。"
        else:
            return f"Unable to infer the reason for {game_name}'s popularity due to insufficient discussion data."

    # 若 lang == 'en' 且 threads 全為英文，直接組合 reason
    if lang == 'en' and threads and all(is_english_thread(t) for t in threads):
        # 直接用第一個討論串標題與前幾則留言組合一段英文 reason
        reason = f"Key discussion for {game_name}: "
        for t in threads[:1]:
            reason += f"{t['title']}. "
            for p in t['posts'][:2]:
                reason += f"{p['author']}: {p['body'][:80]}. "
        return reason.strip()
    # 否則呼叫 LLM
    prompt = PROMPT_HEADER[lang] + f"\n\nGame: {game_name}\nForum thread summary:\n"
    for t in threads:
        prompt += f"\n- {t['title']} ({t['postdate']})"
        for p in t['posts'][:2]:
            prompt += f"\n  - {p['author']}：{p['body'][:80]}"
    try:
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-3.5-turbo"),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=512,
            temperature=0.5
        )
        reason = response.choices[0].message.content.strip()
    except Exception as e:
        print(f"⚠️ LLM 處理失敗: {e}")
        if lang == 'zh-tw':
            reason = f"因為討論資料過少，無法推論 {game_name} 的上榜原因。"
        else:
            reason = f"Unable to infer the reason for {game_name}'s popularity due to insufficient discussion data."
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

def is_threads_expired(objectid, days=7):
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
        return (datetime.utcnow() - dt).days >= days
    except Exception:
        return True

def delete_all_threads_and_i18n(objectid):
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
            time.sleep(1)  # 避免請求過快
            forum_threads = fetch_forum_threads(forum['id'], max_threads=3)

            for thread_info in forum_threads:
                time.sleep(1)  # 避免請求過快
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
    cursor.execute("""
        INSERT INTO forum_threads (objectid, name, threads_json, snapshot_date, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (objectid, name, json.dumps(threads, ensure_ascii=False), datetime.utcnow().strftime("%Y-%m-%d"), datetime.utcnow().isoformat()))
    conn.commit()

    print(f"✅ 已抓取 {len(threads)} 個討論串 objectid={objectid}")
    return threads

def get_threads_by_objectid(objectid):
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

    # 獲取需要處理的遊戲：新進榜 + 沒有討論串資料的遊戲
    def get_games_to_process():
        # 1. 新進榜的遊戲
        cursor.execute("SELECT DISTINCT snapshot_date FROM hot_games ORDER BY snapshot_date DESC LIMIT 2")
        rows = cursor.fetchall()
        new_games = []
        if len(rows) >= 2:
            today, yesterday = rows[0][0], rows[1][0]
            cursor.execute("SELECT objectid, name FROM hot_games WHERE snapshot_date = ?", (today,))
            today_list = cursor.fetchall()
            cursor.execute("SELECT objectid FROM hot_games WHERE snapshot_date = ?", (yesterday,))
            yesterday_ids = [r[0] for r in cursor.fetchall()]
            new_games = [(oid, name) for oid, name in today_list if oid not in yesterday_ids]

        # 2. 今日榜上但沒有討論串資料或翻譯的遊戲
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

        return [(oid, name) for oid, name in all_games.items()]

    games_to_process = get_games_to_process()
    all_results = {}

    for objectid, name in games_to_process:
        print(f"Fetching forum threads for {name} ({objectid}) [{lang}] ...")
        # 1. 判斷討論串是否過期或不存在
        if is_threads_expired(objectid):
            print(f"⏩ 討論串已過期或不存在，重抓並刪除所有語言 reason：objectid={objectid}")
            delete_all_threads_and_i18n(objectid)
            threads = fetch_and_save_threads(objectid, name)
        else:
            threads = get_threads_by_objectid(objectid)

        # 2. 若該語言 reason 不存在，才丟給 LLM
        cursor.execute("SELECT 1 FROM forum_threads_i18n WHERE objectid = ? AND lang = ?", (objectid, lang))
        reason_exists = cursor.fetchone() is not None
        if reason_exists:
            print(f"⏩ 已有新鮮 {lang} reason，跳過 objectid={objectid}")
            continue

        # 3. 用現有 threads 產生 reason
        reason = summarize_reason_with_llm(name, threads)
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

    conn.commit()
    conn.close()
    # 儲存 debug 檔案
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()