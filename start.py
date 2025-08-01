#!/usr/bin/env python3
"""
BGG RAG Daily 應用啟動腳本
用於 Zeabur 部署的主要入口點
"""

import os
import sys
import time
import traceback

def ensure_directories():
    """確保必要的目錄結構存在"""
    directories = [
        'data',
        'data/cache',
        'frontend/public/outputs',
        'outputs/forum_threads'
    ]

    for directory in directories:
        try:
            os.makedirs(directory, exist_ok=True)
            print(f"✅ 確保目錄存在: {directory}")
        except Exception as e:
            print(f"❌ 創建目錄失敗 {directory}: {e}")


def wait_for_database(max_retries=6, delay=2):
    """等待數據庫可用，帶重試機制"""
    print(f"🔄 等待數據庫連接 (最多 {max_retries} 次重試，每次間隔 {delay} 秒)")

    for attempt in range(max_retries):
        try:
            from database import get_db_connection, get_database_config

            config = get_database_config()
            print(f"🔍 第 {attempt + 1}/{max_retries} 次連接嘗試 ({config.get('type', 'unknown')})")

            # 添加連接測試的開始時間
            import time
            start_time = time.time()

            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                result = cursor.fetchone()

                connection_time = time.time() - start_time
                print(f"✅ 數據庫連接成功 (耗時: {connection_time:.2f}秒)")

                if result:
                    return True

        except ImportError as e:
            print(f"❌ 數據庫模組導入失敗 (嘗試 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                print(f"⏳ 等待 {delay} 秒後重試...")
                time.sleep(delay)
            continue
        except Exception as e:
            connection_time = time.time() - start_time if 'start_time' in locals() else 0
            error_msg = str(e)[:200]  # 限制錯誤訊息長度
            print(f"⚠️ 數據庫連接失敗 (嘗試 {attempt + 1}/{max_retries}, 耗時 {connection_time:.2f}秒)")
            print(f"   錯誤詳情: {error_msg}")

            if attempt < max_retries - 1:
                print(f"⏳ 等待 {delay} 秒後重試...")
                time.sleep(delay)
            else:
                print("❌ 所有數據庫連接嘗試都失敗了")
                return False

    return False


def initialize_app():
    """初始化應用但不啟動服務器"""
    try:
        print("🚀 BGG RAG Daily 應用初始化中...")
        print(f"🐍 Python 版本: {sys.version}")
        print(f"📁 工作目錄: {os.getcwd()}")
        print(f"🌐 PORT 環境變數: {os.getenv('PORT', '未設置')}")
        print(f"🗃️ DATABASE_URL 存在: {'是' if os.getenv('DATABASE_URL') else '否'}")

        # 確保目錄結構
        print("📁 創建必要目錄...")
        ensure_directories()

        # 嘗試導入數據庫模組
        print("🗃️ 導入數據庫模組...")
        try:
            from database import init_database
            print("✅ 數據庫模組導入成功")
        except Exception as e:
            print(f"❌ 數據庫模組導入失敗: {e}")
            traceback.print_exc()
            sys.exit(1)

        # 等待數據庫可用
        if not wait_for_database():
            print("❌ 無法連接到數據庫，應用啟動失敗")
            sys.exit(1)

        # 檢查並初始化資料庫表格
        print("🗃️ 檢查資料庫表格結構...")
        try:
            # 檢查必要的表格是否存在
            required_tables = ['hot_games', 'game_detail', 'forum_threads', 'forum_threads_i18n']
            missing_tables = []

            with get_db_connection() as conn:
                cursor = conn.cursor()
                config = get_database_config()

                for table in required_tables:
                    try:
                        if config['type'] == 'postgresql':
                            cursor.execute("""
                                SELECT EXISTS (
                                    SELECT FROM information_schema.tables
                                    WHERE table_schema = 'public'
                                    AND table_name = %s
                                )
                            """, (table,))
                        else:
                            cursor.execute("""
                                SELECT name FROM sqlite_master
                                WHERE type='table' AND name=?
                            """, (table,))

                        result = cursor.fetchone()
                        if not result or (config['type'] == 'postgresql' and not result[0]) or (config['type'] == 'sqlite' and not result):
                            missing_tables.append(table)
                    except Exception as check_error:
                        print(f"⚠️ 檢查表格 {table} 時發生錯誤: {check_error}")
                        missing_tables.append(table)

            if missing_tables:
                print(f"📋 發現缺少的表格: {', '.join(missing_tables)}")
                print("🔧 開始初始化資料庫...")
                init_database()
                print("✅ 資料庫初始化完成")

                # 再次驗證表格是否成功創建
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    config = get_database_config()
                    created_tables = []

                    for table in required_tables:
                        try:
                            if config['type'] == 'postgresql':
                                cursor.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name = %s)", (table,))
                            else:
                                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))

                            result = cursor.fetchone()
                            if result and ((config['type'] == 'postgresql' and result[0]) or (config['type'] == 'sqlite' and result)):
                                created_tables.append(table)
                        except:
                            pass

                    print(f"✅ 成功創建表格: {', '.join(created_tables)}")
                    if len(created_tables) != len(required_tables):
                        print(f"⚠️ 部分表格創建可能失敗，將在運行時重試")
            else:
                print("✅ 所有必要的資料庫表格都已存在")

        except Exception as e:
            error_msg = str(e)[:200]
            print(f"❌ 資料庫檢查/初始化失敗: {error_msg}")
            # 數據庫初始化失敗不一定是致命的，可能表結構已存在
            if "already exists" in error_msg.lower() or "duplicate" in error_msg.lower():
                print("ℹ️ 表格可能已存在，繼續啟動...")
            else:
                print("⚠️ 繼續嘗試啟動應用，運行時會重試初始化...")

        # 嘗試導入 Flask 應用
        print("🌐 導入 Flask 應用...")
        try:
            from app import app
            print("✅ Flask 應用導入成功")
            return app
        except Exception as e:
            print(f"❌ Flask 應用導入失敗: {e}")
            traceback.print_exc()
            sys.exit(1)

    except KeyboardInterrupt:
        print("⏹️ 用戶中斷應用初始化")
        sys.exit(1)
    except Exception as e:
        print(f"💥 應用初始化失敗: {e}")
        traceback.print_exc()
        sys.exit(1)


# 為 gunicorn 暴露應用物件
print("🔧 初始化應用以供 gunicorn 使用...")
try:
    app = initialize_app()
    print("✅ 應用初始化完成，準備交給 gunicorn")

except Exception as e:
    print(f"💥 應用初始化失敗: {e}")
    sys.exit(1)


def main():
    """主啟動函數（用於直接運行）"""
    print("⚠️ 注意：此應用設計為使用 gunicorn 運行")
    print("🚀 直接啟動模式...")

    # 獲取端口號
    port = int(os.getenv('PORT', 5000))
    print(f"🌐 應用將在端口 {port} 啟動")

    # 啟動應用
    print("🚀 啟動 Flask 應用...")
    app.run(host='0.0.0.0', port=port, debug=False)


if __name__ == '__main__':
    main()