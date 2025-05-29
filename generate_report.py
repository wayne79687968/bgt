import sqlite3
import os
from datetime import datetime
import argparse
import re
import json

db_path = "data/bgg_rag.db"
today = datetime.utcnow().strftime("%Y-%m-%d")
yesterday = None

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# 解析參數
parser = argparse.ArgumentParser(description="產生 BGG 熱門桌遊排行榜報告")
parser.add_argument('--detail', choices=['all', 'up', 'new'], default='new', help='詳細資料顯示模式：all=全部, up=只顯示排名上升, new=只顯示新進榜')
parser.add_argument('--lang', choices=['zh-tw', 'en'], default='zh-tw', help='報表語言')
args = parser.parse_args()
detail_mode = args.detail
lang = args.lang

# 報表用語多語言字典
I18N = {
    'zh-tw': {
        'report_title': f"# 📊 BGG 熱門桌遊排行榜報告 - {today}",
        'rank_list': "## 🧱 排行榜列表",
        'table_header': "| 排名 | 桌遊 | 年份 | 排名變化 |",
        'table_sep': "|------|------|------|----------|",
        'new_detail': "## ✨ 新進榜桌遊詳解",
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
        'report_title': f"# 📊 BGG Hot Board Game Ranking Report - {today}",
        'rank_list': "## 🧱 Ranking List",
        'table_header': "| Rank | Game | Year | Change |",
        'table_sep': "|------|------|------|----------|",
        'new_detail': "## ✨ New Entries Details",
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
cursor.execute("SELECT DISTINCT snapshot_date FROM hot_games WHERE snapshot_date < ? ORDER BY snapshot_date DESC LIMIT 1", (today,))
row = cursor.fetchone()
if row:
    yesterday = row[0]

# 抓取今天與昨天的榜單
cursor.execute("SELECT rank, objectid, name, year, thumbnail FROM hot_games WHERE snapshot_date = ? ORDER BY rank ASC", (today,))
today_list = cursor.fetchall()
today_ids = [r[1] for r in today_list]

yesterday_ids = []
if yesterday:
    cursor.execute("SELECT objectid FROM hot_games WHERE snapshot_date = ?", (yesterday,))
    yesterday_ids = [r[0] for r in cursor.fetchall()]

# 組成對照表
markdown = [T['report_title']]

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

# 查詢新進榜詳細資料
markdown.append("")
markdown.append(T['new_detail'])

# 讀取 LLM 上榜推論結果（多語言）
forum_threads_path = f"outputs/forum_threads/forum_threads_{today}.json"
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
cursor2.execute("SELECT objectid, lang, reason FROM forum_threads_i18n WHERE lang = ?", (lang,))
for oid, l, reason in cursor2.fetchall():
    llm_reasons_i18n[oid] = reason
def get_reason(objectid):
    r = llm_reasons_i18n.get(objectid)
    if r:
        return r
    return "" if lang == 'en' else "[暫無翻譯]"

# 決定要顯示詳細資料的 objectid 清單
if detail_mode == 'all':
    detail_ids = [r[1] for r in today_list]
elif detail_mode == 'up':
    detail_ids = []
    for rank, objectid, name, year, thumb in today_list:
        if objectid in yesterday_ids:
            prev_rank = yesterday_ids.index(objectid) + 1
            if prev_rank > rank:
                detail_ids.append(objectid)
elif detail_mode == 'new':
    detail_ids = [r[1] for r in today_list if r[1] not in yesterday_ids]
else:
    detail_ids = []

for objectid in detail_ids:
    cursor.execute("SELECT name, year, rating, rank, weight, minplayers, maxplayers, bestplayers, minplaytime, maxplaytime, categories, mechanics, designers, artists, publishers, image FROM game_detail WHERE objectid = ?", (objectid,))
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
    cursor.execute("SELECT id, comment, sentiment, rating FROM game_comments WHERE objectid = ? ORDER BY id", (objectid,))
    comments = cursor.fetchall()
    # 讀取當前遊戲的多語言留言
    comments_i18n = {}
    if comments:
        comment_ids = [c[0] for c in comments]
        if comment_ids:
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
                    sentiment_map[sentiment].append(f"{score_str}{t}")
                else:
                    sentiment_map[sentiment].append(t)

        # 檢查是否有實際的評論內容（不只是 summary）
        has_actual_comments = len(sentiment_map["positive"] + sentiment_map["neutral"] + sentiment_map["negative"]) > 0

        # 檢查 summary 是否有實際內容（排除無意義的內容）
        meaningless_summaries = [
            "分析總結（無留言）",
            "[暫無翻譯]",
            "",
            "該遊戲並沒有收到任何玩家的評價，無法針對其遊戲性、美術或機制進行分析。",
            "目前沒有任何玩家的評論可供分析。",
            "該遊戲目前沒有任何玩家評價，因此無法進行分析總結。"
        ]
        has_meaningful_summary = (sentiment_map["summary"] and
                                sentiment_map["summary"] not in meaningless_summaries and
                                not sentiment_map["summary"].startswith("分析總結（無") and
                                not sentiment_map["summary"].startswith("該遊戲並沒有收到") and
                                not sentiment_map["summary"].startswith("目前沒有任何") and
                                not sentiment_map["summary"].startswith("該遊戲目前沒有"))

        if has_actual_comments or has_meaningful_summary:
            markdown.append(f"\n{T['comment_analysis']}")
            is_few_comments = len(sentiment_map["positive"] + sentiment_map["neutral"] + sentiment_map["negative"]) < 9
            if is_few_comments and has_actual_comments:
                markdown.append(T['few_comments'])

            def format_comment_section(title, comments):
                if not comments:
                    return ""
                output = [f"**{title}**"]
                for c in comments:
                    output.append(f"> {c}\n")
                return "\n".join(output)

            for section, label in [("positive", T['positive']), ("neutral", T['neutral']), ("negative", T['negative'])]:
                text = format_comment_section(label, sentiment_map[section])
                if text:
                    markdown.append(text)
                    markdown.append("")

            if sentiment_map["summary"]:
                markdown.append(T['summary'])
                markdown.append(f"> {sentiment_map['summary']}")
                markdown.append("")

# 儲存為 Markdown
os.makedirs("frontend/public/outputs", exist_ok=True)
report_filename = f"frontend/public/outputs/report-{today}-{lang}.md"
with open(report_filename, "w", encoding="utf-8") as f:
    f.write("\n".join(markdown).replace("\\n", "\n"))

print(f"✅ 已產出 {lang} 版 Markdown 格式報告：{report_filename}")
