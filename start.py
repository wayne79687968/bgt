#!/usr/bin/env python3
"""
BGG RAG Daily 應用啟動腳本
用於 Zeabur 部署的主要入口點
"""

import os
import sys
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


def main():
    """主啟動函數"""
    try:
        print("🚀 BGG RAG Daily 應用啟動中...")

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

        # 初始化資料庫
        print("🗃️ 初始化資料庫...")
        try:
            init_database()
            print("✅ 資料庫初始化成功")
        except Exception as e:
            print(f"❌ 資料庫初始化失敗: {e}")
            traceback.print_exc()
            sys.exit(1)

        # 嘗試導入 Flask 應用
        print("🌐 導入 Flask 應用...")
        try:
            from app import app
            print("✅ Flask 應用導入成功")
        except Exception as e:
            print(f"❌ Flask 應用導入失敗: {e}")
            traceback.print_exc()
            sys.exit(1)

        print("✅ 應用初始化完成")

        # 獲取端口號
        port = int(os.getenv('PORT', 5000))
        print(f"🌐 應用將在端口 {port} 啟動")

        # 啟動應用
        print("🚀 啟動 Flask 應用...")
        app.run(host='0.0.0.0', port=port, debug=False)

    except Exception as e:
        print(f"💥 應用啟動失敗: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()