from flask import render_template, redirect, url_for, session, jsonify, request, flash
from datetime import datetime

from routes import auth_bp
from email_auth import EmailAuth
from database import get_db_connection, get_database_config, execute_query


email_auth = EmailAuth()


@auth_bp.route('/login', endpoint='login')
@auth_bp.route('/login_email')
def login_page():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return render_template('login_email.html')


@auth_bp.route('/register', endpoint='register')
def register_page():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return render_template('register.html')


@auth_bp.route('/forgot-password', endpoint='forgot_password')
def forgot_password_page():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return render_template('forgot_password.html')


@auth_bp.route('/auth/send-code', methods=['POST'], endpoint='send_verification_code')
def send_verification_code():
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        code_type = data.get('type', 'register')

        if not email:
            return jsonify({'success': False, 'message': '請提供 Email 地址'})

        import re
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            return jsonify({'success': False, 'message': 'Email 格式無效'})

        if code_type in ['login', 'password_reset']:
            user = email_auth.get_user_by_email(email)
            if not user:
                return jsonify({'success': False, 'message': '用戶不存在'})
            if not user['is_active']:
                return jsonify({'success': False, 'message': '帳號已被停用'})
        elif code_type == 'register':
            user = email_auth.get_user_by_email(email)
            if user:
                return jsonify({'success': False, 'message': '此 Email 已註冊'})

        code = email_auth.generate_verification_code()
        if not email_auth.store_verification_code(email, code, code_type):
            return jsonify({'success': False, 'message': '驗證碼儲存失敗'})

        if email_auth.send_verification_code(email, code, code_type):
            return jsonify({'success': True, 'message': '驗證碼已發送'})
        else:
            return jsonify({'success': False, 'message': '郵件發送失敗，請檢查 SMTP 設定'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'系統錯誤: {str(e)}'})


@auth_bp.route('/auth/verify-code', methods=['POST'], endpoint='verify_code')
def verify_code():
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        code = data.get('code', '').strip()
        code_type = data.get('type', 'register')

        if not email or not code:
            return jsonify({'success': False, 'message': '請提供 Email 和驗證碼'})

        if email_auth.verify_code(email, code, code_type):
            return jsonify({'success': True, 'message': '驗證成功'})
        else:
            return jsonify({'success': False, 'message': '驗證碼無效或已過期'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'系統錯誤: {str(e)}'})


@auth_bp.route('/auth/register', methods=['POST'], endpoint='register_user')
def register_user():
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')

        if not email or not password:
            return jsonify({'success': False, 'message': '請提供 Email 和密碼'})
        if len(password) < 6:
            return jsonify({'success': False, 'message': '密碼至少需要6個字符'})

        with get_db_connection() as conn:
            cursor = conn.cursor()
            config = get_database_config()
            execute_query(cursor, """
                SELECT id FROM verification_codes
                WHERE email = ? AND type = 'register' AND used = 1
                AND expires_at > ?
            """, (email, datetime.now().isoformat()), config['type'])
            if not cursor.fetchone():
                return jsonify({'success': False, 'message': '請先完成 Email 验證'})

        name = email.split('@')[0]
        user_data, message = email_auth.create_user(email, password, name)
        if user_data:
            session['user'] = user_data
            session['logged_in'] = True
            session['user_email'] = email

            with get_db_connection() as conn:
                cursor = conn.cursor()
                config = get_database_config()
                execute_query(cursor,
                    "DELETE FROM verification_codes WHERE email = ? AND type = 'register'",
                    (email,), config['type'])
                conn.commit()

            return jsonify({'success': True, 'message': message, 'redirect': url_for('dashboard')})
        else:
            return jsonify({'success': False, 'message': message})
    except Exception as e:
        return jsonify({'success': False, 'message': f'註冊失敗: {str(e)}'})


@auth_bp.route('/auth/login', methods=['POST'], endpoint='login_user')
def login_user():
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        if not email or not password:
            return jsonify({'success': False, 'message': '請提供 Email 和密碼'})

        user_data, message = email_auth.authenticate_user(email, password)
        if user_data:
            session['user'] = user_data
            session['logged_in'] = True
            session['user_email'] = email
            return jsonify({'success': True, 'message': message, 'redirect': url_for('dashboard')})
        else:
            return jsonify({'success': False, 'message': message})
    except Exception as e:
        return jsonify({'success': False, 'message': f'登入失敗: {str(e)}'})


@auth_bp.route('/auth/verify-login', methods=['POST'], endpoint='verify_login')
def verify_login():
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        code = data.get('code', '').strip()
        if not email or not code:
            return jsonify({'success': False, 'message': '請提供 Email 和驗證碼'})

        user_data = email_auth.get_user_by_email(email)
        if not user_data:
            return jsonify({'success': False, 'message': '用戶不存在'})
        if not user_data['is_active']:
            return jsonify({'success': False, 'message': '帳號已被停用'})

        if email_auth.verify_code(email, code, 'login'):
            session['user'] = user_data
            session['logged_in'] = True
            session['user_email'] = email
            return jsonify({'success': True, 'message': '登入成功', 'redirect': url_for('dashboard')})
        else:
            return jsonify({'success': False, 'message': '驗證碼無效或已過期'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'登入失敗: {str(e)}'})


@auth_bp.route('/auth/reset-password', methods=['POST'], endpoint='reset_password')
def reset_password():
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        code = data.get('code', '').strip()
        new_password = data.get('password', '')
        if not email or not code or not new_password:
            return jsonify({'success': False, 'message': '請提供完整資訊'})
        if len(new_password) < 6:
            return jsonify({'success': False, 'message': '密碼至少需要6個字符'})
        if not email_auth.verify_code(email, code, 'password_reset'):
            return jsonify({'success': False, 'message': '驗證碼無效或已過期'})

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                config = get_database_config()
                password_hash = email_auth.hash_password(new_password)
                updated_at = datetime.now().isoformat()
                execute_query(cursor, """
                    UPDATE users SET password_hash = ?, updated_at = ? WHERE email = ?
                """, (password_hash, updated_at, email), config['type'])
                conn.commit()
                return jsonify({'success': True, 'message': '密碼重設成功'})
        except Exception:
            return jsonify({'success': False, 'message': '密碼更新失敗'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'重設失敗: {str(e)}'})


@auth_bp.route('/logout', endpoint='logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


