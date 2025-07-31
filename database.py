#!/usr/bin/env python3
"""
資料庫配置和連接管理模組
支援 SQLite (本地開發) 和 PostgreSQL (生產環境)
"""

import os
import sqlite3
import psycopg2
from urllib.parse import urlparse
from contextlib import contextmanager

def get_database_config():
    """取得資料庫配置"""
    # Zeabur 會自動提供 DATABASE_URL 環境變數
    database_url = os.getenv('DATABASE_URL')
    
    if database_url:
        # 生產環境使用 PostgreSQL
        parsed = urlparse(database_url)
        return {
            'type': 'postgresql',
            'host': parsed.hostname,
            'port': parsed.port,
            'database': parsed.path[1:],  # 移除開頭的 /
            'username': parsed.username,
            'password': parsed.password,
            'url': database_url
        }
    else:
        # 本地開發使用 SQLite
        return {
            'type': 'sqlite',
            'path': 'data/bgg_rag.db'
        }

@contextmanager
def get_db_connection():
    """取得資料庫連接的 context manager"""
    config = get_database_config()
    
    if config['type'] == 'postgresql':
        conn = psycopg2.connect(config['url'])
        try:
            yield conn
        finally:
            conn.close()
    else:
        # SQLite
        os.makedirs('data', exist_ok=True)
        conn = sqlite3.connect(config['path'])
        try:
            yield conn
        finally:
            conn.close()

def init_database():
    """初始化資料庫結構"""
    config = get_database_config()
    print(f"🗃️ 初始化 {config['type']} 資料庫...")
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # PostgreSQL 和 SQLite 的 SQL 語法稍有不同
        if config['type'] == 'postgresql':
            # PostgreSQL 使用 SERIAL 代替 AUTOINCREMENT
            autoincrement_type = "SERIAL PRIMARY KEY"
            text_type = "TEXT"
            timestamp_type = "TIMESTAMP"
        else:
            # SQLite
            autoincrement_type = "INTEGER PRIMARY KEY AUTOINCREMENT"
            text_type = "TEXT"
            timestamp_type = "TIMESTAMP"
        
        # 創建所有資料表
        tables = [
            # 收藏資料表
            f"""
            CREATE TABLE IF NOT EXISTS collection (
                objectid INTEGER PRIMARY KEY,
                name {text_type},
                status {text_type},
                rating REAL,
                wish_priority INTEGER,
                last_sync {timestamp_type}
            )
            """,
            
            # 熱門榜單歷史資料
            f"""
            CREATE TABLE IF NOT EXISTS hot_games (
                snapshot_date {text_type},
                rank INTEGER,
                objectid INTEGER,
                name {text_type},
                year INTEGER,
                thumbnail {text_type},
                PRIMARY KEY (snapshot_date, rank)
            )
            """,
            
            # 詳細資料快取
            f"""
            CREATE TABLE IF NOT EXISTS game_detail (
                objectid INTEGER PRIMARY KEY,
                name {text_type},
                year INTEGER,
                rating REAL,
                rank INTEGER,
                weight REAL,
                minplayers INTEGER,
                maxplayers INTEGER,
                bestplayers {text_type},
                minplaytime INTEGER,
                maxplaytime INTEGER,
                categories {text_type},
                mechanics {text_type},
                designers {text_type},
                artists {text_type},
                publishers {text_type},
                image {text_type},
                last_updated {timestamp_type}
            )
            """,
            
            # BGG 項目資料表
            f"""
            CREATE TABLE IF NOT EXISTS bgg_items (
                id INTEGER,
                name {text_type},
                category {text_type},
                PRIMARY KEY (id, category)
            )
            """,
            
            # 遊戲與分類的關聯表
            f"""
            CREATE TABLE IF NOT EXISTS game_categories (
                objectid INTEGER,
                category_id INTEGER,
                category_type {text_type},
                PRIMARY KEY (objectid, category_id, category_type)
            )
            """,
            
            # 評論快取
            f"""
            CREATE TABLE IF NOT EXISTS game_comments (
                id {autoincrement_type},
                objectid INTEGER,
                comment {text_type},
                rating REAL,
                sentiment {text_type},
                source {text_type},
                created_at {text_type}
            )
            """,
            
            # 討論串與 LLM 推論快取
            f"""
            CREATE TABLE IF NOT EXISTS forum_threads (
                id {autoincrement_type},
                objectid INTEGER,
                name {text_type},
                threads_json {text_type},
                snapshot_date {text_type},
                created_at {text_type}
            )
            """,
            
            # 多語言 i18n：遊戲詳細
            f"""
            CREATE TABLE IF NOT EXISTS game_detail_i18n (
                objectid INTEGER,
                lang {text_type},
                name {text_type},
                categories {text_type},
                mechanics {text_type},
                designers {text_type},
                artists {text_type},
                publishers {text_type},
                PRIMARY KEY (objectid, lang)
            )
            """,
            
            # 多語言 i18n：留言翻譯
            f"""
            CREATE TABLE IF NOT EXISTS game_comments_i18n (
                comment_id INTEGER,
                lang {text_type},
                translated {text_type},
                updated_at {text_type},
                PRIMARY KEY (comment_id, lang)
            )
            """,
            
            # 多語言 i18n：討論串/推論
            f"""
            CREATE TABLE IF NOT EXISTS forum_threads_i18n (
                objectid INTEGER,
                lang {text_type},
                reason {text_type},
                updated_at {text_type},
                PRIMARY KEY (objectid, lang)
            )
            """,
            
            # 用戶資料表
            f"""
            CREATE TABLE IF NOT EXISTS users (
                id {autoincrement_type},
                email {text_type} UNIQUE NOT NULL,
                password_hash {text_type} NOT NULL,
                is_paid INTEGER DEFAULT 0,
                email_verified INTEGER DEFAULT 0,
                created_at {text_type},
                updated_at {text_type}
            )
            """
        ]
        
        for table_sql in tables:
            cursor.execute(table_sql)
        
        # PostgreSQL 需要額外處理 UNIQUE 約束
        if config['type'] == 'postgresql':
            try:
                cursor.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_forum_threads_unique 
                    ON forum_threads (objectid, snapshot_date)
                """)
                cursor.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_bgg_items_unique 
                    ON bgg_items (id, category)
                """)
            except:
                pass  # 約束可能已存在
        
        conn.commit()
        
    print("✅ 資料庫初始化完成")

if __name__ == '__main__':
    init_database()