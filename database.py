#!/usr/bin/env python3
"""
資料庫配置和連接管理模組
支援 PostgreSQL 資料庫
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

    if not database_url:
        raise ValueError("DATABASE_URL 環境變數未設定，請配置 PostgreSQL 連接字串")

    # 解析 PostgreSQL 連接字串
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

def execute_query(cursor, query, params=()):
    """
    執行 PostgreSQL 查詢

    Args:
        cursor: 數據庫游標
        query: SQL 查詢語句（使用 %s 作為占位符）
        params: 查詢參數
    """
    return cursor.execute(query, params)

@contextmanager
def get_db_connection():
    """取得 PostgreSQL 資料庫連接的 context manager"""
    config = get_database_config()
    # PostgreSQL 連接
    try:
        import psycopg2
    except ImportError:
        # 在 Zeabur 環境中，PostgreSQL 套件必須可用
        if os.getenv('DATABASE_URL'):
            raise ImportError("PostgreSQL 套件未安裝，但 DATABASE_URL 已設定")
        else:
            print("⚠️ PostgreSQL 套件未安裝，回退到 SQLite")
            conn = sqlite3.connect('data/bgg_rag.db')
            yield conn
            if 'conn' in locals() and conn:
                conn.close()
            return

        # 添加連接重試邏輯 - 指數退避算法
        max_retries = 10
        initial_delay = 2
        max_delay = 60
        conn = None
        
        try:
            for attempt in range(max_retries):
                try:
                    # 計算動態延遲時間 (指數退避)
                    delay = min(initial_delay * (2 ** attempt), max_delay)
                    
                    if attempt > 0:
                        print(f"⏳ 等待 {delay} 秒後重試...")
                        time.sleep(delay)
                    
                    print(f"🔗 正在建立 PostgreSQL 連接... (嘗試 {attempt + 1}/{max_retries})")
                    print(f"📡 連接目標: {config['host']}:{config['port']}")
                    
                    conn = psycopg2.connect(
                        config['url'],
                        connect_timeout=60,  # 增加連接超時到 60 秒
                        keepalives_idle=600,
                        keepalives_interval=30,
                        keepalives_count=3
                    )
                    
                    # 處理 collation version 警告
                    try:
                        cursor = conn.cursor()
                        cursor.execute("SELECT version()")
                        print("🔍 PostgreSQL 版本檢查完成")
                    except Exception:
                        pass  # 忽略版本檢查錯誤
                    print("✅ PostgreSQL 連接建立成功")
                    yield conn
                    return
                except psycopg2.OperationalError as e:
                    print(f"❌ PostgreSQL 連接失敗 (嘗試 {attempt + 1}/{max_retries}): {e}")
                    
                    # 檢查是否是連接拒絕錯誤
                    if "Connection refused" in str(e):
                        print("🔍 檢測到連接被拒絕，可能是 PostgreSQL 服務尚未就緒")
                        print("🔍 Zeabur PostgreSQL 服務可能需要更多時間啟動")
                    
                    if attempt == max_retries - 1:
                        # 如果有 DATABASE_URL，說明是在 Zeabur 環境，不應該回退
                        if os.getenv('DATABASE_URL'):
                            print("🚨 在 Zeabur 環境中 PostgreSQL 連接完全失敗")
                            print("💡 請檢查 Zeabur PostgreSQL 服務狀態")
                            raise e
                        else:
                            print("🔄 回退到 SQLite 資料庫...")
                            conn = sqlite3.connect('data/bgg_rag.db')
                            print("✅ SQLite 連接建立成功")
                            yield conn
                            return
        finally:
            if conn:
                conn.close()
    else:
        # SQLite 連接
        try:
            conn = sqlite3.connect(config['path'])
            yield conn
        finally:
            if 'conn' in locals() and conn:
                conn.close()

def tables_sql(autoincrement_type, text_type, timestamp_type):
    """返回創建資料表的 SQL 語句列表"""
    return [
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
            password_hash {text_type},
            name {text_type},
            picture {text_type},
            is_verified INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            has_full_access INTEGER DEFAULT 0,
            created_at {text_type},
            updated_at {text_type}
        )
        """,

        # Email 驗證碼表
        f"""
        CREATE TABLE IF NOT EXISTS verification_codes (
            id {autoincrement_type},
            email {text_type} NOT NULL,
            code {text_type} NOT NULL,
            type {text_type} NOT NULL, -- 'register', 'password_reset', 'login'
            expires_at {text_type} NOT NULL,
            used INTEGER DEFAULT 0,
            created_at {text_type} NOT NULL
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
        """,

        # 設計師/繪師資料表
        f"""
        CREATE TABLE IF NOT EXISTS creators (
            id INTEGER PRIMARY KEY,
            bgg_id INTEGER UNIQUE NOT NULL,
            name {text_type} NOT NULL,
            type {text_type} NOT NULL, -- 'designer' or 'artist'
            description {text_type},
            image_url {text_type},
            slug {text_type},
            created_at {text_type},
            updated_at {text_type}
        )
        """,

        # 設計師/繪師的遊戲作品
        f"""
        CREATE TABLE IF NOT EXISTS creator_games (
            creator_id INTEGER,
            bgg_game_id INTEGER,
            game_name {text_type},
            year_published INTEGER,
            rating REAL,
            rank_position INTEGER,
            created_at {text_type},
            PRIMARY KEY (creator_id, bgg_game_id)
        )
        """,

        # 用戶追蹤設計師/繪師
        f"""
        CREATE TABLE IF NOT EXISTS user_follows (
            user_id INTEGER NOT NULL,
            creator_id INTEGER NOT NULL,
            followed_at {text_type},
            PRIMARY KEY (user_id, creator_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """,

        # 新遊戲通知記錄
        f"""
        CREATE TABLE IF NOT EXISTS game_notifications (
            id {autoincrement_type},
            creator_id INTEGER NOT NULL,
            bgg_game_id INTEGER NOT NULL,
            game_name {text_type},
            year_published INTEGER,
            notified_user_ids {text_type}, -- JSON array of user IDs
            created_at {text_type},
            sent_at {text_type}
        )
        """
    ]

def _migrate_existing_schema(cursor, config_type):
    """遷移現有的資料庫 schema"""
    print("🔄 [MIGRATE_SCHEMA] 檢查並遷移現有資料庫 schema...")
    
    migrations = []
    
    if config_type == 'postgresql':
        # 先檢查 users 表是否存在
        try:
            cursor.execute("SELECT to_regclass('public.users')")
            users_table_exists = cursor.fetchone()[0] is not None
        except Exception:
            users_table_exists = False
        
        if not users_table_exists:
            print("✓ [MIGRATE_SCHEMA] 新資料庫，跳過 schema 遷移")
            return
            
        # PostgreSQL 特有的遷移 - 只在表存在時執行
        migrations = [
            # 檢查 users 表是否缺少 name 欄位
            {
                'check': "SELECT column_name FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'name'",
                'migrate': "ALTER TABLE users ADD COLUMN name TEXT",
                'description': '添加 users.name 欄位'
            },
            # 檢查 users 表是否缺少 password_hash 欄位  
            {
                'check': "SELECT column_name FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'password_hash'",
                'migrate': "ALTER TABLE users ADD COLUMN password_hash TEXT",
                'description': '添加 users.password_hash 欄位'
            },
            # 檢查 users 表是否缺少 is_verified 欄位
            {
                'check': "SELECT column_name FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'is_verified'",
                'migrate': "ALTER TABLE users ADD COLUMN is_verified INTEGER DEFAULT 0",
                'description': '添加 users.is_verified 欄位'
            },
            # 檢查 users 表是否缺少 is_active 欄位
            {
                'check': "SELECT column_name FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'is_active'",
                'migrate': "ALTER TABLE users ADD COLUMN is_active INTEGER DEFAULT 1",
                'description': '添加 users.is_active 欄位'
            },
            # 檢查 users 表是否缺少 has_full_access 欄位
            {
                'check': "SELECT column_name FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'has_full_access'",
                'migrate': "ALTER TABLE users ADD COLUMN has_full_access INTEGER DEFAULT 0",
                'description': '添加 users.has_full_access 欄位'
            },
            # 檢查 users 表是否缺少 picture 欄位
            {
                'check': "SELECT column_name FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'picture'",
                'migrate': "ALTER TABLE users ADD COLUMN picture TEXT",
                'description': '添加 users.picture 欄位'
            },
            # 檢查 users 表是否缺少 created_at 欄位
            {
                'check': "SELECT column_name FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'created_at'",
                'migrate': "ALTER TABLE users ADD COLUMN created_at TEXT",
                'description': '添加 users.created_at 欄位'
            },
            # 檢查 users 表是否缺少 updated_at 欄位
            {
                'check': "SELECT column_name FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'updated_at'",
                'migrate': "ALTER TABLE users ADD COLUMN updated_at TEXT",
                'description': '添加 users.updated_at 欄位'
            }
        ]
        
        # 檢查並創建缺失的關鍵表
        critical_tables = [
            {
                'check': "SELECT to_regclass('public.verification_codes')",
                'migrate': """
                    CREATE TABLE verification_codes (
                        id SERIAL PRIMARY KEY,
                        email TEXT NOT NULL,
                        code TEXT NOT NULL,
                        type TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        used INTEGER DEFAULT 0,
                        created_at TEXT NOT NULL
                    )
                """,
                'description': '創建 verification_codes 表'
            }
        ]
        
        # 執行關鍵表檢查
        for table_check in critical_tables:
            try:
                print(f"🔍 [MIGRATE_SCHEMA] 檢查: {table_check['description']}")
                cursor.execute(table_check['check'])
                result = cursor.fetchone()
                
                if not result or result[0] is None:
                    print(f"📝 [MIGRATE_SCHEMA] 執行創建: {table_check['description']}")
                    cursor.execute(table_check['migrate'])
                    print(f"✅ [MIGRATE_SCHEMA] 創建完成: {table_check['description']}")
                else:
                    print(f"✓ [MIGRATE_SCHEMA] 已存在: {table_check['description']}")
                    
            except Exception as e:
                print(f"⚠️ [MIGRATE_SCHEMA] 創建警告 {table_check['description']}: {e}")
                # PostgreSQL 事務出錯時需要回滾
                if config_type == 'postgresql':
                    cursor.execute("ROLLBACK")
                    cursor.execute("BEGIN")
        
        # 用戶表結構遷移 - 從 user_email 轉換為 user_id
        user_table_migrations = [
            {
                'check': "SELECT column_name FROM information_schema.columns WHERE table_name = 'user_follows' AND column_name = 'user_id'",
                'description': '遷移 user_follows 表從 user_email 到 user_id',
                'migrate_sql': [
                    # 1. 創建新表結構
                    """CREATE TABLE IF NOT EXISTS user_follows_new (
                        user_id INTEGER NOT NULL,
                        creator_id INTEGER NOT NULL,
                        followed_at TEXT,
                        PRIMARY KEY (user_id, creator_id),
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                    )""",
                    # 2. 遷移資料 (將 user_email 轉換為 user_id)
                    """INSERT INTO user_follows_new (user_id, creator_id, followed_at)
                       SELECT u.id, uf.creator_id, uf.followed_at 
                       FROM user_follows uf 
                       JOIN users u ON u.email = uf.user_email
                       WHERE EXISTS (SELECT 1 FROM information_schema.columns 
                                   WHERE table_name = 'user_follows' AND column_name = 'user_email')""",
                    # 3. 刪除舊表
                    "DROP TABLE IF EXISTS user_follows",
                    # 4. 重命名新表
                    "ALTER TABLE user_follows_new RENAME TO user_follows"
                ]
            },
            {
                'check': "SELECT column_name FROM information_schema.columns WHERE table_name = 'game_notifications' AND column_name = 'notified_user_ids'",
                'description': '遷移 game_notifications 表從 notified_users 到 notified_user_ids',
                'migrate_sql': [
                    # 1. 添加新欄位
                    "ALTER TABLE game_notifications ADD COLUMN IF NOT EXISTS notified_user_ids TEXT",
                    # 2. 遷移資料 (將 email 轉換為 user_id，這個比較複雜，暫時保留舊欄位)
                    # TODO: 實現 JSON email array 到 user_id array 的轉換
                ]
            }
        ]
        
        for migration in user_table_migrations:
            try:
                print(f"🔍 [MIGRATE_SCHEMA] 檢查: {migration['description']}")
                cursor.execute(migration['check'])
                result = cursor.fetchone()
                
                if not result:
                    print(f"📝 [MIGRATE_SCHEMA] 執行遷移: {migration['description']}")
                    for sql in migration['migrate_sql']:
                        if sql.strip():  # 跳過空的 SQL
                            try:
                                cursor.execute(sql)
                            except Exception as sql_error:
                                print(f"⚠️ [MIGRATE_SCHEMA] SQL 警告: {sql_error}")
                                # 對於資料遷移錯誤，記錄但繼續執行
                                pass
                    print(f"✅ [MIGRATE_SCHEMA] 遷移完成: {migration['description']}")
                else:
                    print(f"✓ [MIGRATE_SCHEMA] 已遷移: {migration['description']}")
                    
            except Exception as e:
                print(f"⚠️ [MIGRATE_SCHEMA] 遷移警告 {migration['description']}: {e}")
                if config_type == 'postgresql':
                    cursor.execute("ROLLBACK")
                    cursor.execute("BEGIN")
    
    for migration in migrations:
        try:
            print(f"🔍 [MIGRATE_SCHEMA] 檢查: {migration['description']}")
            cursor.execute(migration['check'])
            result = cursor.fetchone()
            
            if not result:
                print(f"📝 [MIGRATE_SCHEMA] 執行遷移: {migration['description']}")
                cursor.execute(migration['migrate'])
                print(f"✅ [MIGRATE_SCHEMA] 遷移完成: {migration['description']}")
            else:
                print(f"✓ [MIGRATE_SCHEMA] 已存在: {migration['description']}")
                
        except Exception as e:
            print(f"⚠️ [MIGRATE_SCHEMA] 遷移警告 {migration['description']}: {e}")
            # PostgreSQL 事務出錯時需要回滾
            if config_type == 'postgresql':
                cursor.execute("ROLLBACK")
                cursor.execute("BEGIN")
            # 不阻止其他遷移繼續
    
    print("✅ [MIGRATE_SCHEMA] Schema 遷移檢查完成")

def _create_tables_and_constraints(cursor, tables, config_type):
    """創建資料表和約束的 helper 函數"""
    print("🗃️ [INIT_DATABASE] 開始創建資料表...")
    table_start_time = time.time()
    
    # 先執行 schema 遷移
    _migrate_existing_schema(cursor, config_type)
    
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
    if config_type == 'postgresql':
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

def init_database():
    """初始化資料庫結構"""
    print("🗃️ [INIT_DATABASE] 函數開始執行...")
    print(f"🗃️ [INIT_DATABASE] 當前時間: {datetime.utcnow().strftime('%H:%M:%S')}")

    print("🗃️ [INIT_DATABASE] 正在獲取數據庫配置...")
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
        # 設置 SQL 語法類型
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

        # 處理不同資料庫類型的連接
        if config['type'] == 'postgresql':
            with get_db_connection() as conn:
                connection_time = time.time() - connection_start_time
                print(f"✅ [INIT_DATABASE] PostgreSQL 數據庫連接建立成功 (耗時: {connection_time:.2f}秒)")

                print("🗃️ [INIT_DATABASE] 正在創建游標...")
                cursor = conn.cursor()
                print("✅ [INIT_DATABASE] 游標創建成功")

                # 創建資料表和處理 PostgreSQL 特有約束
                _create_tables_and_constraints(cursor, tables_sql(autoincrement_type, text_type, timestamp_type), config['type'])
                
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
        else:
            # SQLite 連接
            import sqlite3 as _sqlite3
            conn = _sqlite3.connect(config['path'])
            try:
                connection_time = time.time() - connection_start_time
                print(f"✅ [INIT_DATABASE] SQLite 數據庫連接建立成功 (耗時: {connection_time:.2f}秒)")

                print("🗃️ [INIT_DATABASE] 正在創建游標...")
                cursor = conn.cursor()
                print("✅ [INIT_DATABASE] 游標創建成功")

                # 創建資料表
                _create_tables_and_constraints(cursor, tables_sql(autoincrement_type, text_type, timestamp_type), config['type'])
                
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
        connection_time = time.time() - connection_start_time if 'connection_start_time' in locals() else 0
        print(f"❌ [INIT_DATABASE] 數據庫連接或操作失敗 (耗時: {connection_time:.2f}秒): {e}")
        import traceback
        traceback.print_exc()
        raise

    total_time = time.time() - config_start_time
    print("=" * 80)
    print(f"🎉 [INIT_DATABASE] 資料庫初始化完成！")
    print(f"⏱️ [INIT_DATABASE] 總執行時間: {total_time:.2f}秒")
    print("=" * 80)

if __name__ == '__main__':
    init_database()