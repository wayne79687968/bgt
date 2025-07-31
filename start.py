#!/usr/bin/env python3
"""
BGG RAG Daily 應用啟動腳本
用於 Zeabur 部署的主要入口點
"""

import os
import sqlite3
from app import app

def ensure_directories():
    """確保必要的目錄結構存在"""
    directories = [
        'data',
        'data/cache',
        'frontend/public/outputs',
        'outputs/forum_threads'
    ]

    for directory in directories:
        os.makedirs(directory, exist_ok=True)
        print(f"✅ 確保目錄存在: {directory}")

def init_database():
    """初始化資料庫結構（如果需要）"""
    db_path = "data/bgg_rag.db"

    if not os.path.exists(db_path):
        print("🗃️ 初始化資料庫...")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 創建所有必要的表
        print("📊 創建資料表...")
        
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
    else:
        print("✅ 資料庫已存在")

def main():
    """主啟動函數"""
    print("🚀 BGG RAG Daily 應用啟動中...")

    # 確保目錄結構
    ensure_directories()

    # 初始化資料庫
    init_database()

    print("✅ 應用初始化完成")

    # 獲取端口號
    port = int(os.getenv('PORT', 5000))
    print(f"🌐 應用將在端口 {port} 啟動")

    # 啟動應用
    app.run(host='0.0.0.0', port=port, debug=False)

if __name__ == '__main__':
    main()