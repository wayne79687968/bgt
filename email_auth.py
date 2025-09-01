#!/usr/bin/env python3
"""
Email 驗證碼認證系統
支援註冊、登入、密碼重設
"""

import os
import secrets
import hashlib
import smtplib
import logging
from datetime import datetime, timedelta
from functools import wraps
from flask import session, redirect, url_for, request, jsonify
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from database import get_db_connection, execute_query

logger = logging.getLogger(__name__)

class EmailAuth:
    """Email 驗證碼認證系統"""
    
    def __init__(self):
        # SMTP 設定
        self.smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
        self.smtp_port = int(os.getenv('SMTP_PORT', '587'))
        self.smtp_username = os.getenv('SMTP_USERNAME')
        self.smtp_password = os.getenv('SMTP_PASSWORD')
        self.from_email = os.getenv('FROM_EMAIL', self.smtp_username)
        
        # 管理員 email
        self.admin_email = 'wayne79687968@gmail.com'
        
        if not all([self.smtp_username, self.smtp_password]):
            # 只在開發模式顯示配置訊息
            if os.getenv('FLASK_ENV') == 'development':
                logger.info("SMTP Email 服務未配置（驗證碼功能將不可用）")
    
    def generate_verification_code(self, length=6):
        """生成驗證碼"""
        return ''.join([str(secrets.randbelow(10)) for _ in range(length)])
    
    def hash_password(self, password):
        """密碼加密"""
        salt = secrets.token_hex(32)
        password_hash = hashlib.pbkdf2_hmac('sha256', 
                                          password.encode('utf-8'), 
                                          salt.encode('utf-8'), 
                                          100000)
        return salt + password_hash.hex()
    
    def verify_password(self, password, stored_hash):
        """驗證密碼"""
        try:
            salt = stored_hash[:64]  # 前64字符是salt
            stored_password_hash = stored_hash[64:]
            password_hash = hashlib.pbkdf2_hmac('sha256',
                                              password.encode('utf-8'),
                                              salt.encode('utf-8'),
                                              100000)
            return password_hash.hex() == stored_password_hash
        except Exception as e:
            logger.error(f"密碼驗證失敗: {e}")
            return False
    
    def send_verification_code(self, email, code, code_type='register'):
        """發送驗證碼郵件"""
        if not all([self.smtp_username, self.smtp_password]):
            logger.error("SMTP 配置不完整")
            return False
        
        try:
            msg = MIMEMultipart()
            msg['From'] = self.from_email
            msg['To'] = email
            
            if code_type == 'register':
                msg['Subject'] = 'BGG 分析平台 - 註冊驗證碼'
                body = f"""
親愛的用戶：

歡迎註冊 BGG 分析平台！

您的驗證碼是：{code}

此驗證碼將在 10 分鐘後失效。

如果您沒有申請註冊，請忽略此郵件。

BGG 分析平台團隊
                """
            elif code_type == 'login':
                msg['Subject'] = 'BGG 分析平台 - 登入驗證碼'
                body = f"""
親愛的用戶：

您的登入驗證碼是：{code}

此驗證碼將在 10 分鐘後失效。

如果您沒有申請登入，請忽略此郵件。

BGG 分析平台團隊
                """
            elif code_type == 'password_reset':
                msg['Subject'] = 'BGG 分析平台 - 密碼重設驗證碼'
                body = f"""
親愛的用戶：

您的密碼重設驗證碼是：{code}

此驗證碼將在 10 分鐘後失效。

如果您沒有申請密碼重設，請忽略此郵件。

BGG 分析平台團隊
                """
            
            msg.attach(MIMEText(body, 'plain', 'utf-8'))
            
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_username, self.smtp_password)
                server.send_message(msg)
            
            logger.info(f"驗證碼郵件已發送至 {email}")
            return True
            
        except Exception as e:
            logger.error(f"郵件發送失敗: {e}")
            return False
    
    def store_verification_code(self, email, code, code_type='register'):
        """儲存驗證碼到資料庫，如果已存在則更新"""
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                expires_at = (datetime.now() + timedelta(minutes=10)).isoformat()
                created_at = datetime.now().isoformat()
                
                # 嘗試更新現有記錄
                execute_query(cursor, """
                    UPDATE verification_codes 
                    SET code = ?, expires_at = ?, used = 0, created_at = ?
                    WHERE email = ? AND type = ?
                """, (code, expires_at, created_at, email, code_type))
                
                # 如果沒有更新到任何記錄，則插入新記錄
                if cursor.rowcount == 0:
                    execute_query(cursor, """
                        INSERT INTO verification_codes (email, code, type, expires_at, created_at, used)
                        VALUES (?, ?, ?, ?, ?, 0)
                    """, (email, code, code_type, expires_at, created_at))
                
                conn.commit()
                logger.info(f"驗證碼已儲存/更新: {email} ({code_type})")
                return True
                
        except Exception as e:
            logger.error(f"儲存驗證碼失敗: {e}")
            return False
    
    def verify_code(self, email, code, code_type='register'):
        """驗證驗證碼"""
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                execute_query(cursor, """
                    SELECT id, expires_at FROM verification_codes 
                    WHERE email = ? AND code = ? AND type = ? AND used = 0
                """, (email, code, code_type))
                
                result = cursor.fetchone()
                if not result:
                    return False
                
                code_id, expires_at = result
                
                # 檢查是否過期
                if datetime.now() > datetime.fromisoformat(expires_at):
                    return False
                
                # 標記為已使用
                execute_query(cursor, 
                    "UPDATE verification_codes SET used = 1 WHERE id = ?", 
                    (code_id,))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"驗證碼驗證失敗: {e}")
            return False
    
    def create_user(self, email, password, name=None):
        """創建新用戶"""
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # 檢查用戶是否已存在
                execute_query(cursor, "SELECT id FROM users WHERE email = ?", (email,))
                if cursor.fetchone():
                    return None, "用戶已存在"
                
                # 創建用戶
                password_hash = self.hash_password(password)
                created_at = datetime.now().isoformat()
                
                # 判斷是否為管理員
                has_full_access = 1 if email == self.admin_email else 0
                
                execute_query(cursor, """
                    INSERT INTO users (email, password_hash, name, is_verified, has_full_access, created_at, updated_at)
                    VALUES (?, ?, ?, 1, ?, ?, ?)
                """, (email, password_hash, name or email.split('@')[0], has_full_access, created_at, created_at))
                
                # 獲取用戶 ID
                execute_query(cursor, "SELECT id FROM users WHERE email = ?", (email,))
                user_id = cursor.fetchone()[0]
                
                conn.commit()
                
                user_data = {
                    'id': user_id,
                    'email': email,
                    'name': name or email.split('@')[0],
                    'is_verified': True,
                    'has_full_access': bool(has_full_access)
                }
                
                logger.info(f"用戶創建成功: {email}")
                return user_data, "註冊成功"
                
        except Exception as e:
            logger.error(f"創建用戶失敗: {e}")
            return None, f"註冊失敗: {str(e)}"
    
    def authenticate_user(self, email, password):
        """用戶登入驗證"""
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                execute_query(cursor, """
                    SELECT id, email, password_hash, name, is_verified, is_active, has_full_access
                    FROM users WHERE email = ?
                """, (email,))
                
                user = cursor.fetchone()
                if not user:
                    return None, "用戶不存在"
                
                user_id, email, password_hash, name, is_verified, is_active, has_full_access = user
                
                if not is_active:
                    return None, "帳號已被停用"
                
                if not self.verify_password(password, password_hash):
                    return None, "密碼錯誤"
                
                user_data = {
                    'id': user_id,
                    'email': email,
                    'name': name,
                    'is_verified': bool(is_verified),
                    'has_full_access': bool(has_full_access)
                }
                
                return user_data, "登入成功"
                
        except Exception as e:
            logger.error(f"用戶認證失敗: {e}")
            return None, f"登入失敗: {str(e)}"
    
    def get_user_by_email(self, email):
        """根據 email 獲取用戶資訊"""
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                execute_query(cursor, """
                    SELECT id, email, name, is_verified, is_active, has_full_access, created_at
                    FROM users WHERE email = ?
                """, (email,))
                
                user = cursor.fetchone()
                if user:
                    return {
                        'id': user[0],
                        'email': user[1],
                        'name': user[2],
                        'is_verified': bool(user[3]),
                        'is_active': bool(user[4]),
                        'has_full_access': bool(user[5]),
                        'created_at': user[6]
                    }
                return None
                
        except Exception as e:
            logger.error(f"獲取用戶資訊失敗: {e}")
            return None

def login_required(f):
    """登入裝飾器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """管理員權限裝飾器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        
        user = session['user']
        if not user.get('has_full_access', False):
            return jsonify({'error': '需要管理員權限'}), 403
        
        return f(*args, **kwargs)
    return decorated_function

def full_access_required(f):
    """完整權限裝飾器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        
        user = session['user']
        if not user.get('has_full_access', False):
            return jsonify({'error': '此功能需要完整權限'}), 403
        
        return f(*args, **kwargs)
    return decorated_function

def has_full_access():
    """檢查當前用戶是否有完整權限"""
    if 'user' in session:
        return session['user'].get('has_full_access', False)
    return False

def get_current_user():
    """獲取當前用戶資訊"""
    return session.get('user')