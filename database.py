#!/usr/bin/env python3
"""
資料庫配置和連接管理模組
支援 SQLite (本地開發) 和 PostgreSQL (生產環境)
"""

import os
import sqlite3
from urllib.parse import urlparse
from contextlib import contextmanager
import time
from datetime import datetime

def get_database_config():
    """取得資料庫配置"""
    # Zeabur 會自動提供 DATABASE_URL 環境變數
    database_url = os.getenv('DATABASE_URL')

    print(f"🔍 環境檢測: DATABASE_URL = {'存在' if database_url else '不存在'}")
    if database_url:
        print(f"🔍 DATABASE_URL 前綴: {database_url[:20]}...")

    if database_url:
        # 生產環境使用 PostgreSQL
        parsed = urlparse(database_url)
        config = {
            'type': 'postgresql',
            'host': parsed.hostname,
            'port': parsed.port,
            'database': parsed.path[1:],  # 移除開頭的 /
            'username': parsed.username,
            'password': parsed.password,
            'url': database_url
        }
        print(f"✅ 配置 PostgreSQL: {parsed.hostname}:{parsed.port}/{parsed.path[1:]}")
        return config
    else:
        # 本地開發使用 SQLite
        config = {
            'type': 'sqlite',
            'path': 'data/bgg_rag.db'
        }
        print(f"✅ 配置 SQLite: {config['path']}")
        return config

def execute_query(cursor, query, params=(), config_type=None):
    """
    執行相容性查詢，自動處理參數占位符

    Args:
        cursor: 數據庫游標
        query: SQL 查詢語句（使用 ? 作為占位符）
        params: 查詢參數
        config_type: 數據庫類型，如果不提供會自動獲取
    """
    if config_type is None:
        config_type = get_database_config()['type']

    if config_type == 'postgresql':
        # PostgreSQL 使用 %s
        query_pg = query.replace('?', '%s')
        return cursor.execute(query_pg, params)
    else:
        # SQLite 使用 ?
        return cursor.execute(query, params)

@contextmanager
def get_db_connection():
    """取得資料庫連接的 context manager"""
    config = get_database_config()

    if config['type'] == 'postgresql':
        # PostgreSQL 連接
        try:
            import psycopg2
        except ImportError:
            raise ImportError("PostgreSQL 支援需要安裝 psycopg2 套件")

        # 添加連接超時設置
        try:
            print("🔗 正在建立 PostgreSQL 連接...")
            conn = psycopg2.connect(
                config['url'],
                connect_timeout=10  # 連接超時 10 秒
            )
            print("✅ PostgreSQL 連接建立成功")
            yield conn
        except psycopg2.OperationalError as e:
            print(f"❌ PostgreSQL 連接失敗: {e}")
            raise
        finally:
            if 'conn' in locals() and conn:
                conn.close()
    else:
        # SQLite 連接
        try:
            import sqlite3
            conn = sqlite3.connect(config['path'])
            yield conn
        finally:
            if 'conn' in locals() and conn:
                conn.close()

def init_database():
    """初始化資料庫結構"""
    print("🗃️ [INIT_DATABASE] 函數開始執行...")
    print(f"🗃️ [INIT_DATABASE] 當前時間: {datetime.utcnow().strftime('%H:%M:%S') if 'datetime' in globals() else 'unknown'}")

    print("🗃️ [INIT_DATABASE] 正在獲取數據庫配置...")
    import time
    config_start_time = time.time()
    try:
        config = get_database_config()
        config_time = time.time() - config_start_time
        print(f"✅ [INIT_DATABASE] 數據庫配置獲取成功 (耗時: {config_time:.2f}秒): {config['type']}")
    except Exception as e:
        config_time = time.time() - config_start_time
        print(f"❌ [INIT_DATABASE] 數據庫配置獲取失敗 (耗時: {config_time:.2f}秒): {e}")
        raise

    print(f"🗃️ [INIT_DATABASE] 初始化 {config['type']} 資料庫...")

    print("🗃️ [INIT_DATABASE] 正在建立數據庫連接...")
    connection_start_time = time.time()

    try:
        # 為避免 SQLite 上出現異常關閉問題，SQLite 直接開連線不使用 contextmanager
        if config['type'] == 'postgresql':
            with get_db_connection() as conn:
                connection_time = time.time() - connection_start_time
                print(f"✅ [INIT_DATABASE] 數據庫連接建立成功 (耗時: {connection_time:.2f}秒)")

                print("🗃️ [INIT_DATABASE] 正在創建游標...")
                cursor = conn.cursor()
                print("✅ [INIT_DATABASE] 游標創建成功")

                # 以下邏輯統一放到共用區塊
                pass
        else:
            import sqlite3 as _sqlite3
            conn = _sqlite3.connect(config['path'])
            connection_time = time.time() - connection_start_time
            print(f"✅ [INIT_DATABASE] 數據庫連接建立成功 (耗時: {connection_time:.2f}秒)")

            print("🗃️ [INIT_DATABASE] 正在創建游標...")
            cursor = conn.cursor()
            print("✅ [INIT_DATABASE] 游標創建成功")

            # PostgreSQL 和 SQLite 的 SQL 語法稍有不同
            print("🗃️ [INIT_DATABASE] 設置 SQL 語法類型...")
            if config['type'] == 'postgresql':
                # PostgreSQL 使用 SERIAL 代替 AUTOINCREMENT
                autoincrement_type = "SERIAL PRIMARY KEY"
                text_type = "TEXT"
                timestamp_type = "TIMESTAMP"
                print("✅ [INIT_DATABASE] PostgreSQL SQL 語法設置完成")
            else:
                # SQLite
                autoincrement_type = "INTEGER PRIMARY KEY AUTOINCREMENT"
                text_type = "TEXT"
                timestamp_type = "TIMESTAMP"
                print("✅ [INIT_DATABASE] SQLite SQL 語法設置完成")

            # 創建所有資料表
            print("🗃️ [INIT_DATABASE] 開始創建資料表...")
            table_start_time = time.time()

            tables = [
            # 應用設定表
            f"""
            CREATE TABLE IF NOT EXISTS app_settings (
                key {text_type} PRIMARY KEY,
                value {text_type},
                updated_at {timestamp_type}
            )
            """,

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
            """,

            # 報表存儲表
            f"""
            CREATE TABLE IF NOT EXISTS reports (
                id {autoincrement_type},
                report_date {text_type} NOT NULL,
                lang {text_type} NOT NULL DEFAULT 'zh-tw',
                content {text_type} NOT NULL,
                file_size INTEGER DEFAULT 0,
                created_at {text_type} NOT NULL,
                updated_at {text_type} NOT NULL,
                UNIQUE(report_date, lang)
            )
            """
        ]

        print(f"🗃️ [INIT_DATABASE] 準備創建 {len(tables)} 個資料表...")

        for i, table_sql in enumerate(tables, 1):
            table_name = "unknown"
            try:
                # 嘗試從 SQL 中提取表名
                if "CREATE TABLE IF NOT EXISTS" in table_sql:
                    table_name = table_sql.split("CREATE TABLE IF NOT EXISTS")[1].split("(")[0].strip()
            except:
                pass

            print(f"🗃️ [INIT_DATABASE] 創建第 {i}/{len(tables)} 個表: {table_name}")

            try:
                table_exec_start = time.time()
                cursor.execute(table_sql)
                table_exec_time = time.time() - table_exec_start
                print(f"✅ [INIT_DATABASE] 表 {table_name} 創建成功 (耗時: {table_exec_time:.2f}秒)")
            except Exception as e:
                table_exec_time = time.time() - table_exec_start if 'table_exec_start' in locals() else 0
                print(f"❌ [INIT_DATABASE] 表 {table_name} 創建失敗 (耗時: {table_exec_time:.2f}秒): {e}")
                raise

        table_time = time.time() - table_start_time
        print(f"✅ [INIT_DATABASE] 所有資料表創建完成 (總耗時: {table_time:.2f}秒)")

        # PostgreSQL 需要額外處理 UNIQUE 約束
        if config['type'] == 'postgresql':
            print("🗃️ [INIT_DATABASE] 處理 PostgreSQL 特有約束...")
            index_start_time = time.time()

            try:
                print("🗃️ [INIT_DATABASE] 創建 forum_threads 唯一索引...")
                cursor.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_forum_threads_unique
                    ON forum_threads (objectid, snapshot_date)
                """)
                print("✅ [INIT_DATABASE] forum_threads 唯一索引創建成功")

                print("🗃️ [INIT_DATABASE] 創建 bgg_items 唯一索引...")
                cursor.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_bgg_items_unique
                    ON bgg_items (id, category)
                """)
                print("✅ [INIT_DATABASE] bgg_items 唯一索引創建成功")

            except Exception as e:
                print(f"⚠️ [INIT_DATABASE] 索引創建警告 (可能已存在): {e}")
                pass  # 約束可能已存在

            index_time = time.time() - index_start_time
            print(f"✅ [INIT_DATABASE] PostgreSQL 約束處理完成 (耗時: {index_time:.2f}秒)")

        print("🗃️ [INIT_DATABASE] 開始提交事務...")
        commit_start_time = time.time()
        try:
            conn.commit()
            commit_time = time.time() - commit_start_time
            print(f"✅ [INIT_DATABASE] 事務提交成功 (耗時: {commit_time:.2f}秒)")
        except Exception as e:
            commit_time = time.time() - commit_start_time
            print(f"❌ [INIT_DATABASE] 事務提交失敗 (耗時: {commit_time:.2f}秒): {e}")
            raise
        finally:
            try:
                conn.close()
            except Exception:
                pass

    except Exception as e:
        connection_time = time.time() - connection_start_time
        print(f"❌ [INIT_DATABASE] 數據庫連接或操作失敗 (耗時: {connection_time:.2f}秒): {e}")
        import traceback
        traceback.print_exc()
        raise

    total_time = time.time() - config_start_time
    print("=" * 80)
    print(f"�� [INIT_DATABASE] 資料庫初始化完成！")
    print(f"⏱️ [INIT_DATABASE] 總執行時間: {total_time:.2f}秒")
    print("=" * 80)

if __name__ == '__main__':
    init_database()