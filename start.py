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
        # 這裡可以添加基本的資料庫表創建邏輯
        # 目前先創建空的資料庫文件
        conn = sqlite3.connect(db_path)
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