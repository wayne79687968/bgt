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
    print(f"🔄 等待數據庫連接 (最多 {max_retries} 次重試)...")

    for attempt in range(max_retries):
        try:
            from database import get_db_connection, get_database_config

            config = get_database_config()
            print(f"🔍 嘗試連接數據庫 (第 {attempt + 1}/{max_retries} 次) - {config.get('type', 'unknown')}")

            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                if result:
                    print("✅ 數據庫連接成功")
                    return True

        except Exception as e:
            print(f"⚠️ 數據庫連接失敗 (嘗試 {attempt + 1}/{max_retries}): {str(e)[:100]}")
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

        # 初始化資料庫
        print("🗃️ 初始化資料庫結構...")
        try:
            init_database()
            print("✅ 資料庫初始化成功")
        except Exception as e:
            error_msg = str(e)[:200]
            print(f"❌ 資料庫初始化失敗: {error_msg}")
            # 數據庫初始化失敗不一定是致命的，可能表結構已存在
            if "already exists" in error_msg.lower() or "duplicate" in error_msg.lower():
                print("ℹ️ 表格可能已存在，繼續啟動...")
            else:
                print("⚠️ 繼續嘗試啟動應用...")

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