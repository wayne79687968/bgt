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

    print(f"📁 需要創建 {len(directories)} 個目錄")
    for i, directory in enumerate(directories, 1):
        try:
            print(f"📁 [{i}/{len(directories)}] 檢查目錄: {directory}")
            os.makedirs(directory, exist_ok=True)
            print(f"✅ [{i}/{len(directories)}] 確保目錄存在: {directory}")
        except Exception as e:
            print(f"❌ [{i}/{len(directories)}] 創建目錄失敗 {directory}: {e}")
            # 繼續處理其他目錄，不要立即退出

    print("📁 目錄創建任務完成")


def wait_for_database(max_retries=6, delay=2):
    """等待數據庫可用，帶重試機制"""
    print("🔗 開始 wait_for_database 函數...")
    print(f"🔄 等待數據庫連接 (最多 {max_retries} 次重試，每次間隔 {delay} 秒)")

    for attempt in range(max_retries):
        print(f"🔄 開始第 {attempt + 1}/{max_retries} 次連接嘗試...")

        try:
            print("📦 正在導入數據庫函數...")
            from database import get_db_connection, get_database_config
            print("✅ 數據庫函數導入成功")

            print("🗃️ 正在獲取數據庫配置...")
            config = get_database_config()
            print(f"✅ 數據庫配置獲取完成: {config.get('type', 'unknown')}")
            print(f"🔍 第 {attempt + 1}/{max_retries} 次連接嘗試 ({config.get('type', 'unknown')})")

            # 添加連接測試的開始時間
            import time
            start_time = time.time()
            print("⏱️ 開始連接測試...")

            print("🔌 正在建立數據庫連接...")
            with get_db_connection() as conn:
                print("✅ 數據庫連接建立成功，正在創建游標...")
                cursor = conn.cursor()
                print("✅ 游標創建成功，正在執行測試查詢...")
                cursor.execute("SELECT 1")
                print("✅ 測試查詢執行成功，正在獲取結果...")
                result = cursor.fetchone()
                print(f"✅ 查詢結果獲取成功: {result}")

                connection_time = time.time() - start_time
                print(f"✅ 數據庫連接成功 (耗時: {connection_time:.2f}秒)")

                if result:
                    print("🎉 數據庫連接測試通過！")
                    return True
                else:
                    print("⚠️ 查詢返回空結果")

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
            print(f"   錯誤類型: {type(e).__name__}")

            if attempt < max_retries - 1:
                print(f"⏳ 等待 {delay} 秒後重試...")
                time.sleep(delay)
            else:
                print("❌ 所有數據庫連接嘗試都失敗了")
                return False

    print("❌ wait_for_database 函數結束，返回 False")
    return False


def initialize_app():
    """初始化應用但不啟動服務器"""
    print("=" * 60)
    print("🚀 INITIALIZE_APP 函數開始執行")
    print("=" * 60)

    try:
        print("🚀 BGG RAG Daily 應用初始化中...")
        print(f"🐍 Python 版本: {sys.version}")
        print(f"📁 工作目錄: {os.getcwd()}")
        print(f"🌐 PORT 環境變數: {os.getenv('PORT', '未設置')}")
        print(f"🗃️ DATABASE_URL 存在: {'是' if os.getenv('DATABASE_URL') else '否'}")
        print("📋 基本信息檢查完成，開始執行初始化步驟...")

        # 確保目錄結構
        print("📁 [步驟1] 開始創建必要目錄...")
        try:
            import time
            step_start = time.time()
            ensure_directories()
            step_time = time.time() - step_start
            print(f"✅ [步驟1] 目錄創建完成 (耗時: {step_time:.2f}秒)")
        except Exception as e:
            print(f"❌ [步驟1] 目錄創建失敗: {e}")
            raise

        # 嘗試導入數據庫模組
        print("🗃️ [步驟2] 開始導入數據庫模組...")
        try:
            step_start = time.time()
            from database import init_database
            step_time = time.time() - step_start
            print(f"✅ [步驟2] 數據庫模組導入成功 (耗時: {step_time:.2f}秒)")
        except Exception as e:
            print(f"❌ [步驟2] 數據庫模組導入失敗: {e}")
            traceback.print_exc()
            sys.exit(1)

        # 等待數據庫可用
        print("🔗 [步驟3] 開始等待數據庫連接...")
        step_start = time.time()
        try:
            if not wait_for_database():
                print("❌ [步驟3] 無法連接到數據庫，應用啟動失敗")
                sys.exit(1)
            step_time = time.time() - step_start
            print(f"✅ [步驟3] 數據庫連接建立成功 (總耗時: {step_time:.2f}秒)")
        except Exception as e:
            step_time = time.time() - step_start
            print(f"❌ [步驟3] 數據庫連接過程異常 (耗時: {step_time:.2f}秒): {e}")
            traceback.print_exc()
            sys.exit(1)

        # 檢查並初始化資料庫表格
        print("🗃️ [步驟4] 開始檢查資料庫表格結構...")
        step_start = time.time()
        try:
            # 檢查必要的表格是否存在
            required_tables = ['hot_games', 'game_detail', 'forum_threads', 'forum_threads_i18n']
            missing_tables = []

            with get_db_connection() as conn:
                cursor = conn.cursor()
                config = get_database_config()

                for table in required_tables:
                    try:
                        cursor.execute("""
                            SELECT EXISTS (
                                SELECT FROM information_schema.tables
                                WHERE table_schema = 'public'
                                AND table_name = %s
                            )
                        """, (table,))

                        result = cursor.fetchone()
                        if not result or not result[0]:
                            missing_tables.append(table)
                    except Exception as check_error:
                        print(f"⚠️ 檢查表格 {table} 時發生錯誤: {check_error}")
                        missing_tables.append(table)

            if missing_tables:
                print(f"📋 發現缺少的表格: {', '.join(missing_tables)}")
                print("🔧 開始初始化資料庫...")
                init_start = time.time()
                init_database()
                init_time = time.time() - init_start
                print(f"✅ 資料庫初始化完成 (耗時: {init_time:.2f}秒)")

                # 再次驗證表格是否成功創建
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    config = get_database_config()
                    created_tables = []

                    for table in required_tables:
                        try:
                            cursor.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name = %s)", (table,))

                            result = cursor.fetchone()
                            if result and result[0]:
                                created_tables.append(table)
                        except:
                            pass

                    print(f"✅ 成功創建表格: {', '.join(created_tables)}")
                    if len(created_tables) != len(required_tables):
                        print(f"⚠️ 部分表格創建可能失敗，將在運行時重試")
            else:
                print("✅ 所有必要的資料庫表格都已存在")

            step_time = time.time() - step_start
            print(f"✅ [步驟4] 資料庫表格檢查完成 (總耗時: {step_time:.2f}秒)")

        except Exception as e:
            step_time = time.time() - step_start
            error_msg = str(e)[:200]
            print(f"❌ [步驟4] 資料庫檢查/初始化失敗 (耗時: {step_time:.2f}秒): {error_msg}")
            # 數據庫初始化失敗不一定是致命的，可能表結構已存在
            if "already exists" in error_msg.lower() or "duplicate" in error_msg.lower():
                print("ℹ️ 表格可能已存在，繼續啟動...")
            else:
                print("⚠️ 繼續嘗試啟動應用，運行時會重試初始化...")

        # 嘗試導入 Flask 應用
        print("🌐 [步驟5] 開始導入 Flask 應用...")
        step_start = time.time()
        try:
            from app import app
            step_time = time.time() - step_start
            print(f"✅ [步驟5] Flask 應用導入成功 (耗時: {step_time:.2f}秒)")
            return app
        except Exception as e:
            step_time = time.time() - step_start
            print(f"❌ [步驟5] Flask 應用導入失敗 (耗時: {step_time:.2f}秒): {e}")
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
print("=" * 80)
print("🔧 模組層級：開始初始化應用以供 gunicorn 使用...")
print("=" * 80)

import time
module_start_time = time.time()

try:
    print("📞 即將調用 initialize_app() 函數...")
    app = initialize_app()

    module_end_time = time.time()
    total_time = module_end_time - module_start_time
    print("=" * 80)
    print(f"✅ 應用初始化完成，準備交給 gunicorn (總耗時: {total_time:.2f}秒)")
    print(f"🔧 應用物件: {app}")
    print("=" * 80)

except Exception as e:
    module_end_time = time.time()
    total_time = module_end_time - module_start_time
    print("=" * 80)
    print(f"💥 應用初始化失敗 (耗時: {total_time:.2f}秒): {e}")
    print("=" * 80)
    import traceback
    traceback.print_exc()
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