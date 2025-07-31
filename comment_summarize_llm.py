import os
import requests
import xml.etree.ElementTree as ET
import time
from datetime import datetime, timedelta
from openai import OpenAI
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import math
import sys
import json
import argparse
from database import get_db_connection

# 初始化 OpenAI 客戶端
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# DB 連線將在需要時建立

# 解析參數
parser = argparse.ArgumentParser()
parser.add_argument('--lang', choices=['zh-tw', 'en'], default='zh-tw', help='產生評論翻譯語言')
args = parser.parse_args()
lang = args.lang

# 多語言 prompt
PROMPT_HEADER = {
    'zh-tw': """若留言數量不足（低於 10 則），請盡量從中挑出具參考價值的評論進行分析。""",
    'en': """If there are fewer than 10 comments, please select the most valuable ones for analysis."""
}
SYSTEM_MSG = {
    'zh-tw': "你是一位遊戲評論摘要與翻譯助理。請確保回傳的內容是有效的 JSON 格式。",
    'en': "You are a board game review summarization and translation assistant. Please ensure the response is valid JSON."
}

# 設定 requests 重試機制
session = requests.Session()
retries = Retry(
    total=5,
    backoff_factor=1,
    status_forcelist=[500, 502, 503, 504],
    allowed_methods=["GET"],
    raise_on_status=False
)
adapter = HTTPAdapter(max_retries=retries)
session.mount("https://", adapter)
session.mount("http://", adapter)

# 設定
pagesize = 100
min_per_group = 10
max_per_group = 30

cursor.execute("""
CREATE TABLE IF NOT EXISTS game_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    objectid INTEGER,
    comment TEXT,
    rating REAL,
    sentiment TEXT,
    source TEXT,
    created_at TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS game_comments_i18n (
    comment_id INTEGER,
    lang TEXT,
    translated TEXT,
    updated_at TEXT,
    PRIMARY KEY (comment_id, lang)
)
""")

def fetch_page_comments(objectid, page, total_pages=None):
    retry_count = 0
    while True:
        url = f"https://boardgamegeek.com/xmlapi2/thing?id={objectid}&ratingcomments=1&pagesize={pagesize}&page={page}"
        response = session.get(url, timeout=10)
        if response.status_code == 202:
            time.sleep(2)
            continue
        if response.status_code == 429:
            print(f"⚠️ objectid={objectid} page={page} 遇到 rate limit，sleep 10 秒重試")
            time.sleep(10)
            retry_count += 1
            if retry_count > 5:
                print(f"⚠️ objectid={objectid} page={page} rate limit 重試超過 5 次，放棄")
                return [], 0
            continue
        break
    if total_pages is not None and (page < 1 or page > total_pages):
        print(f"⚠️ objectid={objectid} page={page} 超出範圍 1~{total_pages}")
        return [], 0
    if response.status_code != 200:
        print(f"⚠️ objectid={objectid} page={page} status={response.status_code}")
        print(response.content[:200])
        return [], 0
    try:
        root = ET.fromstring(response.content)
    except Exception as e:
        print(f"⚠️ objectid={objectid} page={page} XML 解析失敗: {e}")
        print(response.content[:200])
        return [], 0
    item_node = root.find("item")
    if item_node is None:
        print(f"⚠️ objectid={objectid} page={page} 無 item 節點，API 回傳異常或無資料")
        print(response.content[:200])
        return [], 0
    comments_node = item_node.find("comments")
    if comments_node is None:
        print(f"⚠️ objectid={objectid} page={page} 無 comments 節點")
        return [], 0
    total = int(comments_node.attrib.get("totalitems", 0))
    nodes = comments_node.findall("comment")
    comments = []
    for c in nodes:
        value = c.attrib.get("value", "").strip()
        rating = c.attrib.get("rating", "").strip()
        if value and rating and rating != "N/A":
            comments.append((float(rating), value))
    return comments, total

def fetch_middle_rating_comments(objectid, total_pages):
    collected = []
    visited_pages = set()
    left, right = 1, total_pages
    while left <= right and len(collected) < max_per_group:
        mid = (left + right) // 2
        if mid in visited_pages:
            break
        visited_pages.add(mid)
        comments, _ = fetch_page_comments(objectid, mid, total_pages)
        ratings = [r for r, _ in comments]
        filtered = [(r, text) for r, text in comments if 5 <= r <= 7]
        collected.extend(filtered)
        print(f"[DEBUG] objectid={objectid} page={mid} ratings={ratings}")

        if not comments:
            break

        if ratings and ratings[0] > 7:
            right = mid - 1
        elif ratings and ratings[-1] < 5:
            left = mid + 1
        else:
            # 有落在區間內，左右各再搜尋一次
            # 向左
            l = mid - 1
            while l >= left and len(collected) < max_per_group:
                if l in visited_pages:
                    break
                visited_pages.add(l)
                c, _ = fetch_page_comments(objectid, l, total_pages)
                collected.extend([(r, text) for r, text in c if 5 <= r <= 7])
                l -= 1
            # 向右
            r = mid + 1
            while r <= right and len(collected) < max_per_group:
                if r in visited_pages:
                    break
                visited_pages.add(r)
                c, _ = fetch_page_comments(objectid, r, total_pages)
                collected.extend([(r, text) for r, text in c if 5 <= r <= 7])
                r += 1
            break  # 已經搜尋過區間，結束

    return collected[:max_per_group]



def fetch_all_rating_comments_by_zone(objectid):
    low, mid, high = [], [], []
    _, total_items = fetch_page_comments(objectid, 1)
    total_pages = math.ceil(total_items / pagesize)

    # 分區設定
    low_pages = list(range(1, 6))  # 頁1-5
    high_pages = list(range(max(1, total_pages - 4), total_pages + 1))  # 最後5頁

    def collect(pages, target_list, cond):
        for page in pages:
            if len(target_list) >= max_per_group:
                break
            comments, _ = fetch_page_comments(objectid, page, total_pages)
            for rating, text in comments:
                if cond(rating):
                    target_list.append((rating, text))
                    if len(target_list) >= max_per_group:
                        break

    # 抓各類留言
    collect(low_pages, low, lambda r: r <= 3)
    mid = fetch_middle_rating_comments(objectid, total_pages)
    collect(high_pages, high, lambda r: r >= 8)

    return low[:max_per_group], mid[:max_per_group], high[:max_per_group]

# 查詢 i18n 是否已有翻譯且未過期
def is_i18n_fresh(comment_id, lang, days=7):
    cursor.execute("SELECT updated_at FROM game_comments_i18n WHERE comment_id = ? AND lang = ?", (comment_id, lang))
    row = cursor.fetchone()
    if row and row[0]:
        try:
            dt = datetime.fromisoformat(row[0])
            if datetime.utcnow() - dt < timedelta(days=days):
                return True
        except Exception:
            pass
    return False

def build_prompt(low, mid, high):
    def format_section(title, lst):
        if not lst:
            return f"{title}:\n（無留言）"
        return f"{title}:\n" + "\n".join([f"- {t[1]}" for t in lst[:10]])
    if lang == 'zh-tw':
        full_prompt = f"""{PROMPT_HEADER['zh-tw']}
請閱讀以下桌遊的玩家評價，這些評價已分為三類（低分、中分、高分）：

{format_section('🔴 負評', low)}

{format_section('🟡 中立評價', mid)}

{format_section('🟢 正評', high)}

請你完成以下任務：
1. 為每一類各選出最多 5 則「具有參考價值」的評論（評論中有提到遊戲性、美術、機制等內容）
   - 如果某類評論數量不足 5 則，請盡量選出所有可用的評論
   - 如果某類完全沒有評論，請明確標示「（無留言）」
2. 每則翻譯成繁體中文，保留原語氣與細節
3. 最後產出一段綜合的「LLM 分析總結」，歸納出該遊戲受到喜愛或批評的主要原因

請使用以下 JSON 格式回應：
{{
    "positive": [{{"rating": 8.0, "original": "原始英文評論", "translated": "翻譯後的中文評論"}}, ...],
    "neutral": [{{...}}],
    "negative": [{{...}}],
    "summary": "分析總結（繁體中文）"
}}
"""
    else:
        full_prompt = f"""{PROMPT_HEADER['en']}
Please read the following player reviews for this board game, which are divided into three categories (low, medium, high ratings):

{format_section('🔴 Negative', low)}

{format_section('🟡 Neutral', mid)}

{format_section('🟢 Positive', high)}

Please complete the following tasks:
1. For each category, select up to 5 of the most valuable comments (those mentioning gameplay, art, mechanics, etc.)
   - If there are fewer than 5 comments in a category, select as many as possible
   - If a category has no comments, clearly indicate "(No comments)"
2. Translate each comment into English, preserving the original tone and details
3. Finally, produce a comprehensive "LLM summary" that summarizes the main reasons for the game's praise or criticism

Please respond in the following JSON format:
{{
    "positive": [{{"rating": 8.0, "original": "Original comment", "translated": "English translation"}}, ...],
    "neutral": [{{...}}],
    "negative": [{{...}}],
    "summary": "Summary (English)"
}}
"""
    return full_prompt

def parse_gpt_output(output):
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        try:
            cleaned_output = output.strip()
            if cleaned_output.startswith("```json"):
                cleaned_output = cleaned_output[7:]
            if cleaned_output.endswith("```"):
                cleaned_output = cleaned_output[:-3]
            cleaned_output = cleaned_output.strip()
            data = json.loads(cleaned_output)
        except Exception as e:
            print(f"⚠️ GPT 回應解析錯誤：{e}")
            print("原始回應：")
            print(output)
            return {
                "positive": [],
                "neutral": [],
                "negative": [],
                "summary": "解析錯誤：無法解析 GPT 回應"
            }

    # 確保必要的欄位存在
    required_fields = ["positive", "neutral", "negative", "summary"]
    for field in required_fields:
        if field not in data:
            data[field] = [] if field != "summary" else ""

    # 檢查並修正評論格式
    for sentiment in ["positive", "neutral", "negative"]:
        if not isinstance(data[sentiment], list):
            data[sentiment] = []

        # 確保每個評論都有必要的鍵
        fixed_comments = []
        for comment in data[sentiment]:
            if isinstance(comment, dict):
                # 確保有必要的鍵
                fixed_comment = {
                    "rating": comment.get("rating", 0.0),
                    "original": comment.get("original", ""),
                    "translated": comment.get("translated", "")
                }
                if fixed_comment["original"]:  # 只保留有內容的評論
                    fixed_comments.append(fixed_comment)
        data[sentiment] = fixed_comments

    return data

def analyze_with_gpt(objectid, low, mid, high):
    prompt = build_prompt(low, mid, high)
    try:
        if lang == 'en':
            # 只 summary 用 LLM，評論翻譯直接用原文
            # 先組出正評/中立/負評
            data = {"positive": [], "neutral": [], "negative": [], "summary": ""}
            for sentiment, group in [("positive", high), ("neutral", mid), ("negative", low)]:
                for rating, original in group:
                    data[sentiment].append({"rating": rating, "original": original, "translated": original})
            # summary 用 LLM
            res = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_MSG[lang]},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7
            )
            output = res.choices[0].message.content
            parsed = parse_gpt_output(output)
            data["summary"] = parsed.get("summary", "")
        else:
            res = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_MSG[lang]},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7
            )
            output = res.choices[0].message.content
            data = parse_gpt_output(output)
        if data["summary"] == "解析錯誤：無法解析 GPT 回應":
            print(f"❌ GPT 回應格式錯誤：{objectid}")
            return
        # 直接儲存評論到資料庫（主表只存原文）
        for sentiment, comments in [
            ("positive", data["positive"]),
            ("neutral", data["neutral"]),
            ("negative", data["negative"])
        ]:
            for comment in comments:
                # 檢查必要的鍵是否存在
                if not isinstance(comment, dict):
                    print(f"⚠️ 評論格式錯誤，跳過：{comment}")
                    continue

                original = comment.get("original", "")
                rating = comment.get("rating", None)
                translated = comment.get("translated", "")

                if not original:
                    print(f"⚠️ 評論缺少 original 內容，跳過：{comment}")
                    continue

                # 檢查是否已經存在相同的評論
                cursor.execute("""
                    SELECT id FROM game_comments
                    WHERE objectid = ? AND comment = ? AND sentiment = ? AND rating = ?
                """, (objectid, original, sentiment, rating))
                existing = cursor.fetchone()

                if existing:
                    comment_id = existing[0]
                    print(f"⚠️ 評論已存在，跳過插入：{objectid} - {sentiment}")
                else:
                    cursor.execute("""
                        INSERT INTO game_comments
                        (objectid, comment, rating, sentiment, source, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        objectid,
                        original,
                        rating,
                        sentiment,
                        "bgg-rating",
                        datetime.utcnow().isoformat()
                    ))
                    comment_id = cursor.lastrowid

                # 寫入/更新 i18n
                cursor.execute("""
                    INSERT INTO game_comments_i18n (comment_id, lang, translated, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(comment_id, lang) DO UPDATE SET translated=excluded.translated, updated_at=excluded.updated_at
                """, (comment_id, lang, translated, datetime.utcnow().isoformat()))
        # 儲存總結
        if data["summary"]:
            cursor.execute("""
                INSERT INTO game_comments (objectid, comment, rating, sentiment, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (objectid, '', None, "summary", "bgg-rating", datetime.utcnow().isoformat()))
            comment_id = cursor.lastrowid
            cursor.execute("""
                INSERT INTO game_comments_i18n (comment_id, lang, translated, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(comment_id, lang) DO UPDATE SET translated=excluded.translated, updated_at=excluded.updated_at
            """, (comment_id, lang, data["summary"], datetime.utcnow().isoformat()))
        conn.commit()
        print(f"✅ GPT 分析完成：{objectid} ({lang})")
    except Exception as e:
        print(f"❌ GPT 處理錯誤：{e}")

def is_comments_expired(objectid, days=7):
    cursor.execute("SELECT MAX(created_at) FROM game_comments WHERE objectid = ?", (objectid,))
    row = cursor.fetchone()
    if not row or not row[0]:
        return True
    try:
        dt = datetime.fromisoformat(row[0])
        return (datetime.utcnow() - dt).days >= days
    except Exception:
        return True

def delete_all_comments_and_i18n(objectid):
    # 先找出所有 comment_id
    cursor.execute("SELECT id FROM game_comments WHERE objectid = ?", (objectid,))
    ids = [r[0] for r in cursor.fetchall()]
    if ids:
        cursor.executemany("DELETE FROM game_comments_i18n WHERE comment_id = ?", [(cid,) for cid in ids])
    cursor.execute("DELETE FROM game_comments WHERE objectid = ?", (objectid,))
    conn.commit()

def fetch_and_save_comments(objectid):
    # 這個函數現在只負責重新抓取評論，不儲存到資料庫
    # 實際的儲存會在 analyze_with_gpt 中進行（只儲存精選評論）
    pass

def get_comments_by_objectid(objectid):
    cursor.execute("SELECT id, comment, rating, sentiment FROM game_comments WHERE objectid = ?", (objectid,))
    return cursor.fetchall()

def main(force: bool = False, skip_llm: bool = False):
    cursor.execute("SELECT DISTINCT objectid FROM hot_games WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM hot_games)")
    new_ids = [row[0] for row in cursor.fetchall()]
    for objectid in new_ids:
        print(f"📌 分析遊戲 {objectid} 的有評分留言 ({lang})")

        # 檢查是否已有該語言的 summary
        cursor.execute("SELECT id FROM game_comments WHERE objectid = ? AND sentiment = 'summary' ORDER BY id DESC LIMIT 1", (objectid,))
        row = cursor.fetchone()
        summary_comment_id = row[0] if row else None
        summary_exists = False
        if summary_comment_id:
            cursor.execute("SELECT 1 FROM game_comments_i18n WHERE comment_id = ? AND lang = ?", (summary_comment_id, lang))
            summary_exists = cursor.fetchone() is not None

        # 檢查是否有未翻譯的評論
        cursor.execute("""
            SELECT COUNT(*) FROM game_comments gc
            WHERE gc.objectid = ?
            AND gc.id NOT IN (
                SELECT gci.comment_id FROM game_comments_i18n gci
                WHERE gci.comment_id = gc.id AND gci.lang = ?
            )
        """, (objectid, lang))
        untranslated_count = cursor.fetchone()[0]

        if summary_exists and untranslated_count == 0:
            print(f"⏩ 已有 {lang} 翻譯和 summary，跳過 objectid={objectid}")
            continue

        # 如果有未翻譯的評論，只處理翻譯，不重新抓取
        if summary_exists and untranslated_count > 0:
            print(f"🔄 發現 {untranslated_count} 個未翻譯評論，補充翻譯：objectid={objectid}")
            # 獲取未翻譯的評論
            cursor.execute("""
                SELECT gc.id, gc.comment, gc.rating, gc.sentiment
                FROM game_comments gc
                WHERE gc.objectid = ?
                AND gc.id NOT IN (
                    SELECT gci.comment_id FROM game_comments_i18n gci
                    WHERE gci.comment_id = gc.id AND gci.lang = ?
                )
            """, (objectid, lang))
            untranslated_comments = cursor.fetchall()

            # 為每個未翻譯的評論補充翻譯
            for comment_id, comment, rating, sentiment in untranslated_comments:
                if comment and sentiment != 'summary':  # 跳過空評論和 summary
                    try:
                        if lang == 'en':
                            translated = comment  # 英文直接使用原文
                        else:
                            # 使用 GPT 翻譯單個評論
                            res = client.chat.completions.create(
                                model=OPENAI_MODEL,
                                messages=[
                                    {"role": "system", "content": "你是一位專業的桌遊評論翻譯師，請將以下英文評論翻譯成繁體中文，保持原意和語調。"},
                                    {"role": "user", "content": comment}
                                ],
                                temperature=0.3
                            )
                            translated = res.choices[0].message.content.strip()

                        # 儲存翻譯
                        cursor.execute("""
                            INSERT INTO game_comments_i18n (comment_id, lang, translated, updated_at)
                            VALUES (?, ?, ?, ?)
                            ON CONFLICT(comment_id, lang) DO UPDATE SET translated=excluded.translated, updated_at=excluded.updated_at
                        """, (comment_id, lang, translated, datetime.utcnow().isoformat()))
                        print(f"✅ 已翻譯評論 {comment_id}")
                    except Exception as e:
                        print(f"⚠️ 翻譯評論 {comment_id} 失敗：{e}")

            conn.commit()
            continue

        # 判斷留言是否過期，如果過期就重新處理
        if is_comments_expired(objectid):
            print(f"⏩ 留言已過期，重新處理：objectid={objectid}")
            delete_all_comments_and_i18n(objectid)

        # 直接從 BGG 抓取評論並分組
        print(f"🔍 從 BGG 抓取評論...")
        low, mid, high = fetch_all_rating_comments_by_zone(objectid)

        if not skip_llm:
            analyze_with_gpt(objectid, low, mid, high)
    conn.close()

if __name__ == "__main__":
    force = "--force" in sys.argv
    skip_llm = "--skip-llm" in sys.argv
    main(force, skip_llm)
