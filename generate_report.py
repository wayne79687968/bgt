#!/usr/bin/env python3
import os
import markdown
from datetime import datetime, timedelta, date
import argparse
from database import get_db_connection, get_database_config, execute_query
import json
import glob
import sys
import re

def get_db_connection_sqlite(config):
    """SQLite 連接（備用）"""
    import sqlite3
    import os
    os.makedirs('data', exist_ok=True)
    return sqlite3.connect(config['path'])

def generate_single_report(target_date_str, detail_mode, lang):
    """
    為指定日期產生 BGG 熱門桌遊排行榜報告。
    """
    print(f"🚀 開始產生 {target_date_str} 的 {lang} 版報表，模式: {detail_mode}")

    config = get_database_config()
    print(f"🔧 資料庫類型: {config['type']}")
    print(f"🔧 目標日期: {target_date_str}")

    with get_db_connection() as conn:
        cursor = conn.cursor()
        yesterday = None

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
                'weight': "- **Weight（複雜度）**：{}/5",
                'players': "- **玩家人數**：{}",
                'playtime': "- **遊戲時間**：{} 分鐘",
                'categories': "- **遊戲類型**：{}",
                'mechanics': "- **遊戲機制**：{}",
                'designers': "- **設計師**：{}",
                'artists': "- **美術設計**：{}",
                'publishers': "- **出版商**：{}",
                'few_discussion': "**⚠️ 此為新遊戲，討論較少，推論僅供參考。**\n",
                'no_reason': "**尚無法推論上榜原因**",
                'rank_change_up': "⬆️ +{}",
                'rank_change_down': "⬇️ {}",
                'rank_change_new': "🆕 新進榜",
                'rank_change_same': "➡️ 持平"
            },
            'en': {
                'report_title': "# 📊 BGG Hot Board Games Report - {}",
                'rank_list': "## 🧱 Rankings",
                'table_header': "| Rank | Game | Year | Change |",
                'table_sep': "|------|------|------|--------|",
                'detail_all': "## ✨ All Games Details",
                'detail_up': "## ⬆️ Rising Games Details",
                'detail_new': "## ✨ New Entries Details",
                'detail_up_and_new': "## 🚀 Rising + New Entry Games Details",
                'reason_title': "**📈 Ranking Reason Analysis:**",
                'comment_analysis': "#### 💬 Player Comments Analysis",
                'few_comments': "**⚠️ This is a new game with limited comments, analysis for reference only.**\n",
                'positive': "🟢 Positive",
                'neutral': "🟡 Neutral",
                'negative': "🔴 Negative",
                'summary': "**📘 Analysis Summary:**",
                'rating': "- **Rating**: {}/10",
                'rank': "- **Rank**: {}",
                'weight': "- **Weight (Complexity)**: {}/5",
                'players': "- **Players**: {}",
                'playtime': "- **Play Time**: {} minutes",
                'categories': "- **Categories**: {}",
                'mechanics': "- **Mechanics**: {}",
                'designers': "- **Designers**: {}",
                'artists': "- **Artists**: {}",
                'publishers': "- **Publishers**: {}",
                'few_discussion': "**⚠️ This is a new game with limited discussion, analysis for reference only.**\n",
                'no_reason': "**Unable to determine ranking reason**",
                'rank_change_up': "⬆️ +{}",
                'rank_change_down': "⬇️ {}",
                'rank_change_new': "🆕 New Entry",
                'rank_change_same': "➡️ Same"
            }
        }
        T = I18N[lang]

        # 找出昨天的日期（若存在）
        print("🔍 查找昨天的數據...")
        execute_query(cursor, "SELECT DISTINCT snapshot_date FROM hot_games WHERE snapshot_date < ? ORDER BY snapshot_date DESC LIMIT 1", (target_date_str,), config['type'])
        row = cursor.fetchone()
        if row:
            yesterday = row[0]
            print(f"�� 找到昨天日期: {yesterday}")
        else:
            print("📅 沒有找到昨天的數據")

        # 抓取今天與昨天的榜單
        print(f"🔍 查找 {target_date_str} 的熱門遊戲數據...")
        execute_query(cursor, "SELECT rank, objectid, name, year, thumbnail FROM hot_games WHERE snapshot_date = ? ORDER BY rank ASC", (target_date_str,), config['type'])
        today_list = cursor.fetchall()
        today_ids = [r[1] for r in today_list]

        print(f"📊 找到 {len(today_list)} 個今日熱門遊戲")
        if today_list:
            print(f"📊 排名範圍: 第{today_list[0][0]}名 到 第{today_list[-1][0]}名")
        else:
            print("❌ 沒有找到今日的熱門遊戲數據！")
            return

        yesterday_ids = []
        if yesterday:
            execute_query(cursor, "SELECT objectid FROM hot_games WHERE snapshot_date = ?", (yesterday,), config['type'])
            yesterday_ids = [r[0] for r in cursor.fetchall()]
            print(f"📊 昨日遊戲數量: {len(yesterday_ids)}")

        # 組成對照表
        print("📝 開始生成報表內容...")
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

        print(f"📝 排行榜表格生成完成，共 {len(today_list)} 個遊戲")

        # 讀取 LLM 上榜推論結果（多語言）
        forum_threads_path = f"outputs/forum_threads/forum_threads_{target_date_str}.json"
        llm_reasons = {}
        if os.path.exists(forum_threads_path):
            with open(forum_threads_path, "r", encoding="utf-8") as f:
                forum_data = json.load(f)
                for oid, info in forum_data.items():
                    if info.get("reason"):
                        llm_reasons[int(oid)] = info["reason"]
            print(f"�� 載入 LLM 推論結果: {len(llm_reasons)} 個")
        else:
            print(f"⚠️ 找不到 LLM 推論檔案: {forum_threads_path}")

        # 讀取多語言 reason
        llm_reasons_i18n = {}
        cursor2 = conn.cursor()
        execute_query(cursor2, "SELECT objectid, lang, reason FROM forum_threads_i18n WHERE lang = ?", (lang,), config['type'])
        reasons_data = cursor2.fetchall()
        for oid, l, reason in reasons_data:
            llm_reasons_i18n[oid] = reason
        print(f"📝 載入 {lang} 語言推論結果: {len(llm_reasons_i18n)} 個")

        def get_reason(objectid):
            r = llm_reasons_i18n.get(objectid)
            if r:
                return r
            return "" if lang == 'en' else "[暫無翻譯]"

        # 產生符合條件的桌遊詳細資料 (依照排名順序)
        detailed_games_count = 0
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

            detailed_games_count += 1
            execute_query(cursor, "SELECT name, year, rating, rank, weight, minplayers, maxplayers, bestplayers, minplaytime, maxplaytime, categories, mechanics, designers, artists, publishers, image FROM game_detail WHERE objectid = ?", (objectid,), config['type'])
            detail = cursor.fetchone()
            if not detail:
                print(f"⚠️ 找不到遊戲 {objectid} 的詳細資料")
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

        print(f"📝 詳細資料生成完成，共處理 {detailed_games_count} 個遊戲")

        # 儲存為 Markdown
        output_dir = "frontend/public/outputs"
        print(f"📁 確保輸出目錄存在: {output_dir}")
        os.makedirs(output_dir, exist_ok=True)

        report_filename = f"{output_dir}/report-{target_date_str}-{lang}.md"
        print(f"💾 準備寫入檔案: {report_filename}")

        try:
            with open(report_filename, "w", encoding="utf-8") as f:
                content = "\n".join(markdown).replace("\\n", "\n")
                f.write(content)
                f.flush()  # 強制寫入

            # 驗證檔案是否成功寫入
            if os.path.exists(report_filename):
                file_size = os.path.getsize(report_filename)
                print(f"✅ 已產出 {lang} 版 Markdown 格式報告：{report_filename}")
                print(f"📊 檔案大小: {file_size} bytes")
                print(f"📊 內容行數: {len(markdown)} 行")

                # 同時保存報表內容到資料庫（持久化）
                try:
                    print(f"💾 保存報表內容到資料庫...")
                    final_content = "\n".join(markdown).replace("\\n", "\n")
                    current_time = datetime.now().isoformat()

                    if config['type'] == 'postgresql':
                        cursor.execute("""
                            INSERT INTO reports (report_date, lang, content, file_size, created_at, updated_at)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT (report_date, lang) DO UPDATE SET
                                content = EXCLUDED.content,
                                file_size = EXCLUDED.file_size,
                                updated_at = EXCLUDED.updated_at
                        """, (target_date_str, lang, final_content, file_size, current_time, current_time))
                    else:
                        cursor.execute("""
                            INSERT INTO reports (report_date, lang, content, file_size, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?)
                            ON CONFLICT (report_date, lang) DO UPDATE SET
                                content = excluded.content,
                                file_size = excluded.file_size,
                                updated_at = excluded.updated_at
                        """, (target_date_str, lang, final_content, file_size, current_time, current_time))

                    conn.commit()
                    print(f"✅ 報表內容已保存到資料庫 (日期: {target_date_str}, 語言: {lang})")

                except Exception as db_error:
                    print(f"⚠️ 保存到資料庫失敗，但檔案已成功寫入: {db_error}")

                # 讀取檔案前幾行驗證
                try:
                    with open(report_filename, "r", encoding="utf-8") as f:
                        first_line = f.readline().strip()
                        print(f"📝 檔案首行: {first_line}")
                except Exception as e:
                    print(f"⚠️ 讀取檔案首行失敗: {e}")
            else:
                print(f"❌ 檔案寫入失敗！檔案不存在: {report_filename}")
        except Exception as e:
            print(f"❌ 寫入檔案時發生錯誤: {e}")
            import traceback
            print(f"❌ 錯誤詳情: {traceback.format_exc()}")

        print(f"🔒 資料庫連接已關閉")


def main():
    """
    主程式，負責解析參數、計算需產生的報告日期，並呼叫產生器。
    """
    print("🚀 BGG 報表產生器啟動")
    print(f"🔧 當前工作目錄: {os.getcwd()}")
    print(f"🔧 Python 版本: {os.sys.version}")

    parser = argparse.ArgumentParser(description="產生 BGG 熱門桌遊排行榜報告")
    parser.add_argument('--detail', choices=['all', 'up', 'new', 'up_and_new'], default='new', help='詳細資料顯示模式：all=全部, up=只顯示排名上升, new=只顯示新進榜, up_and_new=排名上升+新進榜')
    parser.add_argument('--lang', choices=['zh-tw', 'en'], default='zh-tw', help='報表語言')
    parser.add_argument('--force', action='store_true', help='強制產生今日報表，即使已存在')
    args = parser.parse_args()
    detail_mode = args.detail
    lang = args.lang
    force_generate = args.force

    print(f"🔧 執行參數: detail={detail_mode}, lang={lang}, force={force_generate}")

    # 數據庫初始化由 scheduler.py 負責，這裡不需要重複調用以避免並發問題
    print("🗃️ [GENERATE_REPORT] 跳過數據庫初始化（由 scheduler.py 負責）")
    print(f"🗃️ [GENERATE_REPORT] 當前時間: {datetime.utcnow().strftime('%H:%M:%S')}")
    print("🗃️ [GENERATE_REPORT] 開始主要處理...")

    output_dir = "frontend/public/outputs"
    print(f"📁 檢查輸出目錄: {output_dir}")

    # 檢查目錄權限
    try:
        os.makedirs(output_dir, exist_ok=True)
        print(f"✅ 輸出目錄已確保存在")

        # 測試寫入權限
        test_file = os.path.join(output_dir, "test_write_permission.tmp")
        try:
            with open(test_file, "w") as f:
                f.write("test")
            os.remove(test_file)
            print(f"✅ 輸出目錄寫入權限正常")
        except Exception as e:
            print(f"❌ 輸出目錄寫入權限測試失敗: {e}")
            print(f"❌ 目錄完整路徑: {os.path.abspath(output_dir)}")
            import stat
            if os.path.exists(output_dir):
                dir_stat = os.stat(output_dir)
                print(f"📊 目錄權限: {oct(dir_stat.st_mode)}")

    except Exception as e:
        print(f"❌ 創建輸出目錄失敗: {e}")
        import traceback
        print(f"❌ 錯誤詳情: {traceback.format_exc()}")

    report_files = glob.glob(os.path.join(output_dir, f"report-*-{lang}.md"))
    print(f"📂 找到現有報表檔案: {len(report_files)} 個")

    last_report_date = None
    if report_files:
        dates = []
        for f in report_files:
            match = re.search(r'report-(\d{4}-\d{2}-\d{2})', os.path.basename(f))
            if match:
                dates.append(date.fromisoformat(match.group(1)))
        if dates:
            last_report_date = max(dates)
            print(f"📅 最新報表日期: {last_report_date}")

    today_date = datetime.utcnow().date()
    print(f"📅 今日日期: {today_date}")

    dates_to_generate = []
    start_date = None

    # 檢查今日報表是否已存在
    today_report_file = f"report-{today_date}-{lang}.md"
    today_report_path = os.path.join(output_dir, today_report_file)

    if os.path.exists(today_report_path) and not force_generate:
        print(f"✅ 今日報表已存在: {today_report_path}")
        file_size = os.path.getsize(today_report_path)
        file_mtime = os.path.getmtime(today_report_path)
        mtime_str = datetime.fromtimestamp(file_mtime).strftime('%Y-%m-%d %H:%M:%S')
        print(f"📊 檔案資訊: {file_size} bytes，修改時間: {mtime_str}")
        print("ℹ️ 如需重新產生，請使用 --force 參數")
        return

    if force_generate:
        # 強制模式：直接產生今日報表
        print("🔄 強制模式：將產生今日報表")
        dates_to_generate = [today_date]
    elif last_report_date is None:
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
                print(f"📅 資料庫中最早日期: {earliest_date_str}")

        except Exception as e:
            print(f"❌ 檢查數據庫時發生錯誤: {e}")
            print("請確保已執行數據抓取流程並且數據庫中有熱門遊戲數據。")
            import traceback
            print(f"❌ 錯誤詳情: {traceback.format_exc()}")
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
        # 正常模式：產生比最新報表更新的日期
        start_date = last_report_date + timedelta(days=1)
        print(f"📅 開始產生日期: {start_date}")

    # 如果不是強制模式，按正常邏輯產生日期範圍
    if not force_generate and start_date:
        current_date = start_date
        while current_date <= today_date:
            dates_to_generate.append(current_date)
            current_date += timedelta(days=1)

    print(f"📋 待產生報表日期: {[d.strftime('%Y-%m-%d') for d in dates_to_generate]}")

    if not dates_to_generate:
        if force_generate:
            print("❌ 強制模式失敗：無法確定要產生的日期")
        else:
            print("✅ 報告已是最新狀態。")
            print("💡 如果要重新產生今日報表，請使用 --force 選項")
        return

    # 檢查資料庫連線
    print("🔍 開始檢查數據並產生報表...")
    with get_db_connection() as conn_check:
        cursor_check = conn_check.cursor()

        config = get_database_config()

        for dt in dates_to_generate:
            target_date_str = dt.strftime("%Y-%m-%d")
            print(f"\n📊 處理日期: {target_date_str}")

            if force_generate:
                # 強制模式：直接產生報表，不檢查數據是否存在
                print(f"--- 強制產生 {target_date_str} 的報告 ---")
                try:
                    generate_single_report(target_date_str, detail_mode, lang)
                    print(f"✅ {target_date_str} 報表產生完成")
                except Exception as e:
                    print(f"❌ {target_date_str} 報表產生失敗: {e}")
                    import traceback
                    print(f"❌ 錯誤詳情: {traceback.format_exc()}")
            else:
                # 正常模式：檢查數據是否存在
                execute_query(cursor_check, "SELECT COUNT(*) FROM hot_games WHERE snapshot_date = ?", (target_date_str,), config['type'])
                count_result = cursor_check.fetchone()
                data_count = count_result[0] if count_result else 0
                print(f"📊 {target_date_str} 的數據量: {data_count}")

                if data_count > 0:
                    print(f"--- 正在產生 {target_date_str} 的報告 ---")
                    try:
                        generate_single_report(target_date_str, detail_mode, lang)
                        print(f"✅ {target_date_str} 報表產生完成")
                    except Exception as e:
                        print(f"❌ {target_date_str} 報表產生失敗: {e}")
                        import traceback
                        print(f"❌ 錯誤詳情: {traceback.format_exc()}")
                else:
                    print(f"--- 找不到 {target_date_str} 的資料，跳過報告產生 ---")

    print("🎉 報表產生任務完成！")

if __name__ == "__main__":
    main()
