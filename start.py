#!/usr/bin/env python3
"""
BGG RAG Daily 應用啟動腳本
用於 Zeabur 部署的主要入口點
"""

import os
from database import init_database
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