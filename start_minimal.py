#!/usr/bin/env python3
"""
最小化測試啟動腳本
用於診斷 Zeabur 部署問題
"""

import os
import sys
from flask import Flask

# 設置環境變數
os.environ['SKIP_MODULE_DB_INIT'] = '1'

# 創建最小 Flask 應用
app = Flask(__name__)

@app.route('/health/quick')
def health_quick():
    return {'status': 'ok', 'test': 'minimal'}

@app.route('/')
def index():
    return '<h1>Minimal Test App Running!</h1>'

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)