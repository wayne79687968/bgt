#!/usr/bin/env python3
"""
調試版啟動腳本 - 逐步添加功能找出阻塞點
"""

import os
import sys
from flask import Flask

# 設置環境變數
os.environ['SKIP_MODULE_DB_INIT'] = '1'

print("🔧 調試版啟動中...", flush=True)

# 創建 Flask 應用
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'debug-key')

print("✅ Flask 基本配置完成", flush=True)

# 測試導入 1: database 模組
try:
    print("🔍 測試導入 database...", flush=True)
    from database import get_database_config
    print("✅ database 導入成功", flush=True)
except Exception as e:
    print(f"❌ database 導入失敗: {e}", flush=True)

# 測試導入 2: email_auth 模組
try:
    print("🔍 測試導入 email_auth...", flush=True)
    from email_auth import EmailAuth
    print("✅ email_auth 導入成功", flush=True)
except Exception as e:
    print(f"❌ email_auth 導入失敗: {e}", flush=True)

# 測試導入 3: 其他模組
try:
    print("🔍 測試導入其他常用模組...", flush=True)
    from datetime import datetime
    import json
    import requests
    print("✅ 其他模組導入成功", flush=True)
except Exception as e:
    print(f"❌ 其他模組導入失敗: {e}", flush=True)

@app.route('/')
def index():
    return '<h1>Debug Test App - Gradual Import Testing</h1>'

@app.route('/health/quick')
def health_quick():
    return {
        'status': 'ok',
        'test': 'debug_version',
        'imports': 'testing_gradual'
    }

@app.route('/test-db-config')
def test_db_config():
    """測試資料庫配置（不連接）"""
    try:
        from database import get_database_config
        config = get_database_config()
        return {
            'status': 'success',
            'db_type': config.get('type'),
            'host': config.get('host')
        }
    except Exception as e:
        return {
            'status': 'error',
            'message': str(e)
        }

print("✅ 調試版應用準備完成", flush=True)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)