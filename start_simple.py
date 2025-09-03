#!/usr/bin/env python3
"""
極簡化的 BGG RAG Daily 應用啟動腳本
專為 Zeabur 部署優化，避免任何阻塞操作
"""

import os
import sys

# 設置關鍵環境變數（在任何導入之前）
os.environ['SKIP_MODULE_DB_INIT'] = '1'

def create_app():
    """創建 Flask 應用的工廠函數"""
    
    # 創建基本目錄（非阻塞）
    try:
        os.makedirs('data', exist_ok=True)
        os.makedirs('frontend/public/outputs', exist_ok=True)
    except:
        pass  # 忽略錄創建錯誤
    
    # 延遲導入，避免模組級初始化
    try:
        from app import app
        return app
    except Exception as e:
        print(f"❌ Flask 應用導入失敗: {e}", file=sys.stderr)
        raise

# 為 gunicorn 暴露應用物件
app = create_app()

if __name__ == '__main__':
    # 直接運行模式
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)