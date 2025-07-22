#!/usr/bin/env python3
import os
import sqlite3
from datetime import datetime, date
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from dotenv import load_dotenv
import subprocess
import logging
import glob
import re

# 嘗試導入 markdown，如果失敗則使用簡單的文字顯示
try:
    import markdown
    MARKDOWN_AVAILABLE = True
except ImportError:
    MARKDOWN_AVAILABLE = False
    print("Warning: markdown module not available. Reports will be displayed as plain text.")

# 載入環境變數
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key-here')

# 設定日誌
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 登入憑證
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'password')

DB_PATH = "data/bgg_rag.db"

def get_report_by_date(report_date, lang='zh-tw'):
    """獲取指定日期的報表內容"""
    try:
        report_dir = "frontend/public/outputs"
        if not os.path.exists(report_dir):
            return None, "報表目錄不存在"

        # 尋找指定日期的報表
        report_filename = f"report-{report_date}-{lang}.md"
        report_path = os.path.join(report_dir, report_filename)

        if not os.path.exists(report_path):
            return None, f"找不到 {report_date} 的報表"

        with open(report_path, 'r', encoding='utf-8') as f:
            content = f.read()

        return content, report_filename
    except Exception as e:
        logger.error(f"讀取報表失敗: {e}")
        return None, f"讀取報表失敗: {e}"

def get_latest_report():
    """獲取最新的報表內容"""
    try:
        # 尋找最新的報表檔案
        report_dir = "frontend/public/outputs"
        if not os.path.exists(report_dir):
            return None, "報表目錄不存在"

        # 尋找最新的繁體中文報表
        report_files = [f for f in os.listdir(report_dir) if f.endswith('-zh-tw.md')]
        if not report_files:
            return None, "找不到報表檔案"

        # 取得最新的報表
        latest_file = sorted(report_files)[-1]
        report_path = os.path.join(report_dir, latest_file)

        with open(report_path, 'r', encoding='utf-8') as f:
            content = f.read()

        return content, latest_file
    except Exception as e:
        logger.error(f"讀取報表失敗: {e}")
        return None, f"讀取報表失敗: {e}"

def get_available_dates():
    """獲取所有可用的報表日期"""
    try:
        report_dir = "frontend/public/outputs"
        if not os.path.exists(report_dir):
            return []

        report_files = glob.glob(os.path.join(report_dir, "report-*-zh-tw.md"))
        dates = []
        for f in report_files:
            match = re.search(r'report-(\d{4}-\d{2}-\d{2})', os.path.basename(f))
            if match:
                dates.append(match.group(1))

        return sorted(dates, reverse=True)
    except Exception as e:
        logger.error(f"獲取可用日期失敗: {e}")
        return []

def generate_report():
    """產生新的報表"""
    try:
        logger.info("開始產生報表...")

        # 執行報表產生腳本
        result = subprocess.run([
            'python3', 'generate_report.py',
            '--lang', 'zh-tw',
            '--detail', 'all'
        ], capture_output=True, text=True, timeout=300)

        if result.returncode == 0:
            logger.info("報表產生成功")
            return True, "報表產生成功"
        else:
            logger.error(f"報表產生失敗: {result.stderr}")
            return False, f"報表產生失敗: {result.stderr}"
    except subprocess.TimeoutExpired:
        logger.error("報表產生超時")
        return False, "報表產生超時"
    except Exception as e:
        logger.error(f"報表產生異常: {e}")
        return False, f"報表產生異常: {e}"

def run_scheduler():
    """執行完整的排程任務"""
    try:
        logger.info("開始執行完整排程任務...")

        # 執行排程腳本
        result = subprocess.run([
            'python3', 'scheduler.py', '--run-now',
            '--detail', 'all',
            '--lang', 'zh-tw'
        ], capture_output=True, text=True, timeout=1800)  # 30分鐘超時

        if result.returncode == 0:
            logger.info("排程任務執行成功")
            return True, "排程任務執行成功"
        else:
            logger.error(f"排程任務執行失敗: {result.stderr}")
            return False, f"排程任務執行失敗: {result.stderr}"
    except subprocess.TimeoutExpired:
        logger.error("排程任務執行超時")
        return False, "排程任務執行超時"
    except Exception as e:
        logger.error(f"排程任務執行異常: {e}")
        return False, f"排程任務執行異常: {e}"

@app.route('/')
def index():
    if 'logged_in' not in session:
        return redirect(url_for('login'))

    # 獲取選擇的日期，預設為今日
    selected_date = request.args.get('date')
    if not selected_date:
        selected_date = datetime.now().strftime('%Y-%m-%d')

    # 獲取指定日期的報表
    content, filename = get_report_by_date(selected_date)

    # 如果找不到指定日期的報表，嘗試獲取最新報表
    if content is None:
        content, filename = get_latest_report()

    if content is None:
        return render_template('error.html', error=filename)

    # 將 Markdown 轉換為 HTML（如果可用）
    if MARKDOWN_AVAILABLE:
        html_content = markdown.markdown(content, extensions=['tables', 'fenced_code'])
    else:
        # 如果沒有 markdown 模組，使用 <pre> 標籤顯示原始文字
        html_content = f"<pre>{content}</pre>"

    # 獲取所有可用日期
    available_dates = get_available_dates()

    return render_template('report.html',
                         content=html_content,
                         filename=filename,
                         selected_date=selected_date,
                         available_dates=available_dates,
                         last_updated=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

@app.route('/settings')
def settings():
    """設定頁面"""
    if 'logged_in' not in session:
        return redirect(url_for('login'))

    available_dates = get_available_dates()
    return render_template('settings.html', available_dates=available_dates)

@app.route('/api/run-scheduler', methods=['POST'])
def api_run_scheduler():
    """API端點：執行完整排程任務"""
    if 'logged_in' not in session:
        return jsonify({'success': False, 'message': '未登入'}), 401

    success, message = run_scheduler()
    return jsonify({'success': success, 'message': message})

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['logged_in'] = True
            flash('登入成功！', 'success')
            return redirect(url_for('index'))
        else:
            flash('帳號或密碼錯誤！', 'error')

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    flash('已登出', 'info')
    return redirect(url_for('login'))

@app.route('/generate')
def generate():
    if 'logged_in' not in session:
        return redirect(url_for('login'))

    success, message = generate_report()
    if success:
        flash(message, 'success')
    else:
        flash(message, 'error')

    return redirect(url_for('index'))

@app.route('/health')
def health():
    """健康檢查端點"""
    return {'status': 'ok', 'timestamp': datetime.now().isoformat()}

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)