#!/usr/bin/env python3
"""
簡化的 BGG RAG Daily 應用啟動腳本
專為 Zeabur 部署優化，移除複雜的初始化邏輯
"""

import os
import sys

def ensure_basic_directories():
    """只創建最基本必需的目錄"""
    directories = ['data', 'frontend/public/outputs']
    
    for directory in directories:
        try:
            os.makedirs(directory, exist_ok=True)
        except Exception:
            pass  # 忽略目錄創建錯誤，運行時再處理

def initialize_app():
    """最小化的應用初始化"""
    print("🚀 BGG RAG Daily 應用啟動中...")
    
    # 創建基本目錄
    ensure_basic_directories()
    
    # 檢查 PostgreSQL 配置
    database_url = os.getenv('DATABASE_URL')
    if database_url:
        print("🔍 檢測到 DATABASE_URL，使用 PostgreSQL")
        # 添加 PostgreSQL 服務等待邏輯
        postgres_wait = int(os.getenv('POSTGRES_STARTUP_WAIT', '60'))
        print(f"⏳ 等待 PostgreSQL 服務啟動 ({postgres_wait} 秒)...")
        import time
        time.sleep(postgres_wait)
        
        # 嘗試初始化 PostgreSQL 資料庫
        try:
            print("🗃️ 初始化 PostgreSQL 資料庫...")
            from database import init_database
            init_database()
            print("✅ PostgreSQL 資料庫初始化完成")
        except Exception as e:
            print(f"⚠️ 資料庫初始化警告: {e}")
    else:
        print("❌ 錯誤：未檢測到 DATABASE_URL，請設定 PostgreSQL 連線")
    
    # 直接導入應用，讓 Flask 處理其餘初始化
    try:
        from app import app
        print("✅ Flask 應用導入成功")
        return app
    except Exception as e:
        print(f"❌ Flask 應用導入失敗: {e}")
        # 不要退出，讓 gunicorn 重試
        raise

# 為 gunicorn 暴露應用物件
print("🔧 正在初始化應用...")
try:
    app = initialize_app()
    print("✅ 應用初始化完成")
except Exception as e:
    print(f"❌ 應用初始化失敗: {e}")
    # 重新拋出異常讓 gunicorn 處理
    raise

if __name__ == '__main__':
    # 直接運行模式
    port = int(os.getenv('PORT', 5000))
    print(f"🌐 應用將在端口 {port} 啟動")
    app.run(host='0.0.0.0', port=port, debug=False)