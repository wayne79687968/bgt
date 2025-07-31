import os
from datetime import datetime, date, timedelta
import argparse
import re
import json
import glob
from database import get_db_connection, get_database_config

def get_db_conn():
    """相容性函數：直接使用 get_db_connection 的結果"""
    # 這個函數現在直接調用統一的連接函數
    from contextlib import contextmanager

    @contextmanager
    def db_conn():
        with get_db_connection() as conn:
            yield conn

    # 返回連接（為了保持向後相容性）
    config = get_database_config()
    if config['type'] == 'postgresql':
        import psycopg2
        return psycopg2.connect(config['url'])
    else:
        import sqlite3
        import os
        os.makedirs('data', exist_ok=True)
        return sqlite3.connect(config['path'])

def execute_query(cursor, query, params, config_type=None):
    """執行相容性查詢，自動處理參數佔位符"""
    if config_type is None:
        config_type = get_database_config()['type']

    if config_type == 'postgresql':
        # PostgreSQL 使用 %s
        query_pg = query.replace('?', '%s')
        cursor.execute(query_pg, params)
    else:
        # SQLite 使用 ?
        cursor.execute(query, params)

def generate_single_report(target_date_str, detail_mode, lang):
    """
    為指定日期產生 BGG 熱門桌遊排行榜報告。
    """
    yesterday = None

    conn = get_db_conn()
    cursor = conn.cursor()
    config = get_database_config()

    # 報表用語多語言字典
    I18N = {
        'zh-tw': {
            'report_title': "# 📊 BGG 熱門桌遊排行榜報告 - {}",
            'rank_list': "## 🧱 排行榜列表",
            'table_header': "| 排名 | 桌遊 | 年份 | 排名變化 |",
            'table_sep': "|------|------|------|----------|",
            'detail_all': "## ✨ 所有桌遊詳解",
            'detail_up': "## ⬆️ 排名上升桌遊詳解",
            'detail_new': "## ✨ 新進榜桌遊詳解",
            'detail_up_and_new': "## 🚀 排名上升 + 新進榜桌遊詳解",
            'reason_title': "**📈 上榜原因推論：**",
            'comment_analysis': "#### 💬 玩家留言分析",
            'few_comments': "**⚠️ 此為新遊戲，評論數量較少，分析僅供參考。**\n",
            'positive': "🟢 正評",
            'neutral': "🟡 中立評價",
            'negative': "🔴 負評",
            'summary': "**📘 分析總結：**",
            'rating': "- **Rating**：{}/10",
            'rank': "- **Rank**：{}",
            'weight': "- **重度**：{}/5",
            'players': "- **人數**：{}～{} 人（最佳：{}）",
            'playtime': "- **時間**：{}～{} 分鐘",
            'categories': "- **分類**：{}",
            'mechanics': "- **機制**：{}",
            'designers': "- **設計師**：{}",
            'artists': "- **美術**：{}",
            'publishers': "- **發行商**：{}",
        },
        'en': {
            'report_title': "# 📊 BGG Hot Board Game Ranking Report - {}",
            'rank_list': "## 🧱 Ranking List",
            'table_header': "| Rank | Game | Year | Change |",
            'table_sep': "|------|------|------|----------|",
            'detail_all': "## ✨ All Games Details",
            'detail_up': "## ⬆️ Rising Games Details",
            'detail_new': "## ✨ New Entries Details",
            'detail_up_and_new': "## 🚀 Rising + New Entries Details",
            'reason_title': "**📈 Reason for Ranking (LLM):**",
            'comment_analysis': "#### 💬 Player Comment Analysis",
            'few_comments': "**⚠️ This is a new game with few comments. Analysis is for reference only.**\n",
            'positive': "🟢 Positive",
            'neutral': "🟡 Neutral",
            'negative': "🔴 Negative",
            'summary': "**📘 Summary:**",
            'rating': "- **Rating**: {}/10",
            'rank': "- **Rank**: {}",
            'weight': "- **Weight**: {}/5",
            'players': "- **Players**: {}-{} (Best: {})",
            'playtime': "- **Playtime**: {}-{} min",
            'categories': "- **Categories**: {}",
            'mechanics': "- **Mechanics**: {}",
            'designers': "- **Designers**: {}",
            'artists': "- **Artists**: {}",
            'publishers': "- **Publishers**: {}",
        }
    }
    T = I18N[lang]

    # 找出昨天的日期（若存在）
    execute_query(cursor, "SELECT DISTINCT snapshot_date FROM hot_games WHERE snapshot_date < ? ORDER BY snapshot_date DESC LIMIT 1", (target_date_str,), config['type'])
    row = cursor.fetchone()
    if row:
        yesterday = row[0]

    # 抓取今天與昨天的榜單
    execute_query(cursor, "SELECT rank, objectid, name, year, thumbnail FROM hot_games WHERE snapshot_date = ? ORDER BY rank ASC", (target_date_str,), config['type'])
    today_list = cursor.fetchall()
    today_ids = [r[1] for r in today_list]

    yesterday_ids = []
    if yesterday:
        execute_query(cursor, "SELECT objectid FROM hot_games WHERE snapshot_date = ?", (yesterday,), config['type'])
        yesterday_ids = [r[0] for r in cursor.fetchall()]

    # 組成對照表
    markdown = [T['report_title'].format(target_date_str)]

    markdown.append(T['rank_list'])
    markdown.append(T['table_header'])
    markdown.append(T['table_sep'])

    for rank, objectid, name, year, thumb in today_list:
        if objectid not in yesterday_ids:
            change = "🆕"
        else:
            prev_rank = yesterday_ids.index(objectid) + 1
            if prev_rank > rank:
                change = f"⬆️ {prev_rank - rank}"
            elif prev_rank < rank:
                change = f"⬇️ {rank - prev_rank}"
            else:
                change = "⏺️"
        year_str = str(year) if year else "-"
        url = f"https://boardgamegeek.com/boardgame/{objectid}"
        image_md = f'<img src="{thumb}" width="50"/>' if thumb else ""
        anchor = f"{name}-{year_str}".replace(' ', '-').replace('(', '').replace(')', '').replace('.', '').replace('–', '-').replace('—', '-')
        anchor = re.sub(r'[^a-zA-Z0-9\-]', '', anchor)
        bgg_link = f"[🔗]({url})"
        markdown.append(f"| {rank} | [{name}](#{anchor}) {bgg_link}<br>{image_md} | {year_str} | {change} |")

    # 查詢詳細資料區塊標題
    markdown.append("")
    if detail_mode == 'all':
        markdown.append(T['detail_all'])
    elif detail_mode == 'up':
        markdown.append(T['detail_up'])
    elif detail_mode == 'new':
        markdown.append(T['detail_new'])
    elif detail_mode == 'up_and_new':
        markdown.append(T['detail_up_and_new'])
    else:
        markdown.append(T['detail_new'])  # 預設

    # 讀取 LLM 上榜推論結果（多語言）
    forum_threads_path = f"outputs/forum_threads/forum_threads_{target_date_str}.json"
    llm_reasons = {}
    if os.path.exists(forum_threads_path):
        with open(forum_threads_path, "r", encoding="utf-8") as f:
            forum_data = json.load(f)
            for oid, info in forum_data.items():
                if info.get("reason"):
                    llm_reasons[int(oid)] = info["reason"]
    # 讀取多語言 reason
    llm_reasons_i18n = {}
    cursor2 = conn.cursor()
    execute_query(cursor2, "SELECT objectid, lang, reason FROM forum_threads_i18n WHERE lang = ?", (lang,), config['type'])
    for oid, l, reason in cursor2.fetchall():
        llm_reasons_i18n[oid] = reason
    def get_reason(objectid):
        r = llm_reasons_i18n.get(objectid)
        if r:
            return r
        return "" if lang == 'en' else "[暫無翻譯]"

    # 產生符合條件的桌遊詳細資料 (依照排名順序)
    for current_rank, objectid, name, year, thumb in today_list:
        is_new = objectid not in yesterday_ids
        is_up = False
        if objectid in yesterday_ids:
            prev_rank = yesterday_ids.index(objectid) + 1
            if prev_rank > current_rank:
                is_up = True

        should_display = (
            (detail_mode == 'all') or
            (detail_mode == 'up' and is_up) or
            (detail_mode == 'new' and is_new) or
            (detail_mode == 'up_and_new' and (is_up or is_new))
        )

        if not should_display:
            continue

        execute_query(cursor, "SELECT name, year, rating, rank, weight, minplayers, maxplayers, bestplayers, minplaytime, maxplaytime, categories, mechanics, designers, artists, publishers, image FROM game_detail WHERE objectid = ?", (objectid,), config['type'])
        detail = cursor.fetchone()
        if not detail:
            continue
        (
            name, year, rating, rank, weight,
            minp, maxp, bestp, minpt, maxpt,
            cats, mechs, designers, artists, pubs, image
        ) = detail
        name = name or f"Boardgame {objectid}"
        url = f"https://boardgamegeek.com/boardgame/{objectid}"
        anchor = f"{name}-{year}".replace(' ', '-').replace('(', '').replace(')', '').replace('.', '').replace('–', '-').replace('—', '-')
        anchor = re.sub(r'[^a-zA-Z0-9\-]', '', anchor)
        markdown.append(f"### <a id='{anchor}'></a>{name} ({year})")
        if image:
            markdown.append(f"![{name}]({image})")
        rating_str = f"{round(rating, 2):.2f}" if rating is not None else "-"
        weight_str = f"{round(weight, 2):.2f}" if weight is not None else "-"
        markdown.append(T['rating'].format(rating_str))
        markdown.append(T['rank'].format(rank))
        markdown.append(T['weight'].format(weight_str))
        markdown.append(T['players'].format(minp, maxp, bestp))
        markdown.append(T['playtime'].format(minpt, maxpt))
        markdown.append(T['categories'].format(cats))
        markdown.append(T['mechanics'].format(mechs))
        markdown.append(T['designers'].format(designers))
        markdown.append(T['artists'].format(artists))
        markdown.append(T['publishers'].format(pubs))
        markdown.append("")
        # 顯示 LLM 上榜推論（多語言）
        reason = get_reason(objectid)
        if reason:
            markdown.append(T['reason_title'])
            markdown.append(f"> {reason}\n")

        # 加入留言分析內容（多語言）
        execute_query(cursor, "SELECT id, comment, sentiment, rating FROM game_comments WHERE objectid = ? ORDER BY id", (objectid,), config['type'])
        comments = cursor.fetchall()
        # 讀取當前遊戲的多語言留言
        comments_i18n = {}
        if comments:
            comment_ids = [c[0] for c in comments]
            if comment_ids:
                if config['type'] == 'postgresql':
                    placeholders = ','.join(['%s'] * len(comment_ids))
                    cursor2.execute(f"SELECT comment_id, translated FROM game_comments_i18n WHERE comment_id IN ({placeholders}) AND lang = %s", comment_ids + [lang])
                else:
                    placeholders = ','.join(['?'] * len(comment_ids))
                    cursor2.execute(f"SELECT comment_id, translated FROM game_comments_i18n WHERE comment_id IN ({placeholders}) AND lang = ?", comment_ids + [lang])
                for cid, translated in cursor2.fetchall():
                    comments_i18n[cid] = translated

        # 只有當有評論時才顯示評論分析區塊
        if comments:
            sentiment_map = {"positive": [], "neutral": [], "negative": [], "summary": ""}
            for cid, original, sentiment, rating in comments:
                t = comments_i18n.get(cid)
                if not t:  # 檢查 None 或空字串
                    if lang == 'en':
                        t = original  # 英文顯示原文
                    else:
                        t = "[暫無翻譯]"
                if sentiment == "summary":
                    sentiment_map["summary"] = t
                else:
                    if rating is not None and rating > 0:  # 只有當評分大於 0 時才顯示分數
                        score = int(rating) if rating == int(rating) else round(rating, 1)
                        if lang == 'en':
                            score_str = f"(Rating: {score})"
                        else:
                            score_str = f"（{score}分）"
                        sentiment_map.setdefault(sentiment, []).append(f"{t} {score_str}")
                    else:
                        sentiment_map.setdefault(sentiment, []).append(t)

            markdown.append(T['comment_analysis'])
            if len(comments) < 5 and any(c[2] != 'summary' for c in comments):
                 markdown.append(T['few_comments'])

            def format_comment_section(title, comments):
                if comments:
                    return [f"**{title}**"] + [f"> {c}" for c in comments] + [""]
                return []

            markdown.extend(format_comment_section(T['positive'], sentiment_map.get("positive")))
            markdown.extend(format_comment_section(T['neutral'], sentiment_map.get("neutral")))
            markdown.extend(format_comment_section(T['negative'], sentiment_map.get("negative")))

            if sentiment_map.get("summary"):
                markdown.append(f"**{T['summary']}**")
                markdown.append(f"> {sentiment_map['summary']}")
                markdown.append("")
        markdown.append("---")

    # 儲存為 Markdown
    os.makedirs("frontend/public/outputs", exist_ok=True)
    report_filename = f"frontend/public/outputs/report-{target_date_str}-{lang}.md"
    with open(report_filename, "w", encoding="utf-8") as f:
        f.write("\n".join(markdown).replace("\\n", "\n"))

    conn.close()
    print(f"✅ 已產出 {lang} 版 Markdown 格式報告：{report_filename}")


def main():
    """
    主程式，負責解析參數、計算需產生的報告日期，並呼叫產生器。
    """
    parser = argparse.ArgumentParser(description="產生 BGG 熱門桌遊排行榜報告")
    parser.add_argument('--detail', choices=['all', 'up', 'new', 'up_and_new'], default='new', help='詳細資料顯示模式：all=全部, up=只顯示排名上升, new=只顯示新進榜, up_and_new=排名上升+新進榜')
    parser.add_argument('--lang', choices=['zh-tw', 'en'], default='zh-tw', help='報表語言')
    args = parser.parse_args()
    detail_mode = args.detail
    lang = args.lang

    # 確保數據庫已初始化
    try:
        from database import init_database
        print("🗃️ 確保數據庫已初始化...")
        init_database()
        print("✅ 數據庫初始化完成")
    except Exception as e:
        print(f"❌ 數據庫初始化失敗: {e}")
        return

    output_dir = "frontend/public/outputs"
    os.makedirs(output_dir, exist_ok=True)

    report_files = glob.glob(os.path.join(output_dir, f"report-*-{lang}.md"))

    last_report_date = None
    if report_files:
        dates = []
        for f in report_files:
            match = re.search(r'report-(\d{4}-\d{2}-\d{2})', os.path.basename(f))
            if match:
                dates.append(date.fromisoformat(match.group(1)))
        if dates:
            last_report_date = max(dates)

    today_date = datetime.utcnow().date()

    dates_to_generate = []
    start_date = None

    if last_report_date is None:
        print("🟠 找不到任何已產生的報表，將嘗試從資料庫中最早的日期開始產生。")
        # Find the earliest date in the database with error handling
        try:
            with get_db_connection() as conn_check:
                cursor_check = conn_check.cursor()
                config_check = get_database_config()

                # 檢查 hot_games 表是否存在且有數據
                if config_check['type'] == 'postgresql':
                    cursor_check.execute("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables
                            WHERE table_name = 'hot_games'
                        )
                    """)
                else:
                    cursor_check.execute("""
                        SELECT name FROM sqlite_master
                        WHERE type='table' AND name='hot_games'
                    """)

                table_exists = cursor_check.fetchone()
                if not table_exists or (isinstance(table_exists, tuple) and not table_exists[0]):
                    print("❌ hot_games 表不存在。請先執行數據抓取流程（fetch_hotgames.py）。")
                    return

                execute_query(cursor_check, "SELECT MIN(snapshot_date) FROM hot_games", (), config_check['type'])
                earliest_date_result = cursor_check.fetchone()
                earliest_date_str = earliest_date_result[0] if earliest_date_result else None

        except Exception as e:
            print(f"❌ 檢查數據庫時發生錯誤: {e}")
            print("請確保已執行數據抓取流程並且數據庫中有熱門遊戲數據。")
            return

        if earliest_date_str:
            start_date = date.fromisoformat(earliest_date_str)
        else:
            print("❌ 資料庫中沒有任何資料，無法產生報表。")
            print("請先執行完整的數據抓取流程：")
            print("1. python fetch_hotgames.py")
            print("2. python fetch_details.py")
            print("3. python fetch_bgg_forum_threads.py")
            return
    else:
        start_date = last_report_date + timedelta(days=1)

    if start_date:
        current_date = start_date
        while current_date <= today_date:
            dates_to_generate.append(current_date)
            current_date += timedelta(days=1)

    if not dates_to_generate:
        print("✅ 報告已是最新狀態。")
        return

    # 檢查資料庫連線
    with get_db_connection() as conn_check:
        cursor_check = conn_check.cursor()

        config = get_database_config()

        for dt in dates_to_generate:
            target_date_str = dt.strftime("%Y-%m-%d")
            execute_query(cursor_check, "SELECT 1 FROM hot_games WHERE snapshot_date = ? LIMIT 1", (target_date_str,), config['type'])
            if cursor_check.fetchone():
                print(f"--- 正在產生 {target_date_str} 的報告 ---")
                generate_single_report(target_date_str, detail_mode, lang)
            else:
                print(f"--- 找不到 {target_date_str} 的資料，跳過報告產生 ---")

if __name__ == "__main__":
    main()
