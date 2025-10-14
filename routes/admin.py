from flask import request, jsonify
from datetime import datetime
import os

from routes import admin_bp
from database import get_database_config, init_database, get_db_connection


@admin_bp.route('/api/init-database', methods=['POST'])
def api_init_database():
    """手動初始化資料庫端點"""
    try:
        auth_header = request.headers.get('Authorization')
        expected_token = os.getenv('CRON_SECRET_TOKEN', 'default-cron-secret')
        if not auth_header or auth_header != f'Bearer {expected_token}':
            return jsonify({'success': False, 'message': '未授權訪問', 'timestamp': datetime.now().isoformat()}), 401

        config = get_database_config()
        init_database()

        with get_db_connection() as conn:
            cursor = conn.cursor()
            # 檢查 users.name 欄位
            try:
                cursor.execute("SELECT name FROM users LIMIT 1")
                users_name_exists = True
            except Exception:
                users_name_exists = False
            # 檢查 verification_codes 表
            try:
                cursor.execute("SELECT COUNT(*) FROM verification_codes")
                verification_codes_exists = True
            except Exception:
                verification_codes_exists = False

        result = {
            'success': True,
            'message': '資料庫初始化完成',
            'timestamp': datetime.now().isoformat(),
            'database_type': config['type'],
            'tables_verified': {
                'users_name_column': users_name_exists,
                'verification_codes_table': verification_codes_exists
            }
        }
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'message': f'資料庫初始化失敗: {str(e)}', 'timestamp': datetime.now().isoformat()}), 500


