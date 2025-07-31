import sqlite3
import os

os.makedirs("data", exist_ok=True)
db_path = "data/bgg_rag.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# 收藏資料表
cursor.execute("""
CREATE TABLE IF NOT EXISTS collection (
    objectid INTEGER PRIMARY KEY,
    name TEXT,
    status TEXT,
    rating REAL,
    wish_priority INTEGER,
    last_sync TIMESTAMP
)
""")

# 熱門榜單歷史資料
cursor.execute("""
CREATE TABLE IF NOT EXISTS hot_games (
    snapshot_date TEXT,
    rank INTEGER,
    objectid INTEGER,
    name TEXT,
    year INTEGER,
    thumbnail TEXT,
    PRIMARY KEY (snapshot_date, rank)
)
""")

# 詳細資料快取
cursor.execute("""
CREATE TABLE IF NOT EXISTS game_detail (
    objectid INTEGER PRIMARY KEY,
    name TEXT,
    year INTEGER,
    rating REAL,
    rank INTEGER,
    weight REAL,
    minplayers INTEGER,
    maxplayers INTEGER,
    bestplayers TEXT,
    minplaytime INTEGER,
    maxplaytime INTEGER,
    categories TEXT,
    mechanics TEXT,
    designers TEXT,
    artists TEXT,
    publishers TEXT,
    image TEXT,
    last_updated TIMESTAMP
)
""")

# BGG 項目資料表
cursor.execute("""
CREATE TABLE IF NOT EXISTS bgg_items (
    id INTEGER,
    name TEXT,
    category TEXT,
    PRIMARY KEY (id, category),
    UNIQUE (id, category)
)
""")

# 遊戲與分類的關聯表
cursor.execute("""
CREATE TABLE IF NOT EXISTS game_categories (
    objectid INTEGER,
    category_id INTEGER,
    category_type TEXT,
    FOREIGN KEY (objectid) REFERENCES game_detail (objectid),
    FOREIGN KEY (category_id, category_type) REFERENCES bgg_items (id, category),
    PRIMARY KEY (objectid, category_id, category_type)
)
""")

# 評論快取
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

# 討論串與 LLM 推論快取
cursor.execute("""
CREATE TABLE IF NOT EXISTS forum_threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    objectid INTEGER,
    name TEXT,
    threads_json TEXT,
    snapshot_date TEXT,
    created_at TEXT,
    UNIQUE(objectid, snapshot_date)
)
""")

# 多語言 i18n：遊戲詳細
cursor.execute("""
CREATE TABLE IF NOT EXISTS game_detail_i18n (
    objectid INTEGER,
    lang TEXT,
    name TEXT,
    categories TEXT,
    mechanics TEXT,
    designers TEXT,
    artists TEXT,
    publishers TEXT,
    PRIMARY KEY (objectid, lang)
)
""")

# 多語言 i18n：留言翻譯
cursor.execute("""
CREATE TABLE IF NOT EXISTS game_comments_i18n (
    comment_id INTEGER,
    lang TEXT,
    translated TEXT,
    updated_at TEXT,
    PRIMARY KEY (comment_id, lang)
)
""")

# 多語言 i18n：討論串/推論
cursor.execute("""
CREATE TABLE IF NOT EXISTS forum_threads_i18n (
    objectid INTEGER,
    lang TEXT,
    reason TEXT,
    updated_at TEXT,
    PRIMARY KEY (objectid, lang)
)
""")

# 用戶資料表
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    is_paid INTEGER DEFAULT 0,
    email_verified INTEGER DEFAULT 0,
    created_at TEXT,
    updated_at TEXT
)
""")

conn.commit()
conn.close()
print("✅ 資料庫初始化完成")

