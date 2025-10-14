from flask import jsonify
from datetime import datetime
import os
import sys

from routes import health_bp
from database import get_db_connection


@health_bp.route('/health')
def health():
    """健康檢查端點 - 快速響應版本"""
    health_info = {
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'python_version': sys.version,
        'port': os.getenv('PORT', 'not set'),
        'database_url_configured': 'yes' if os.getenv('DATABASE_URL') else 'no'
    }

    if os.getenv('SKIP_DB_HEALTH_CHECK') != '1':
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                health_info['database'] = 'connected'
        except Exception as e:
            health_info['database'] = f'error: {str(e)[:50]}'
    else:
        health_info['database'] = 'check_skipped'

    return jsonify(health_info)


@health_bp.route('/health/quick')
def health_quick():
    return {
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'app': 'running'
    }


