#!/usr/bin/env python3
"""
Google OAuth 認證服務
處理 Google 登入流程和用戶管理
"""

import os
import json
import logging
from datetime import datetime
from functools import wraps
from flask import session, redirect, url_for, request, jsonify
import google.auth.transport.requests
import google.oauth2.id_token
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
import requests

from database import get_db_connection, execute_query

logger = logging.getLogger(__name__)

class GoogleAuth:
    """Google OAuth 認證管理"""
    
    def __init__(self):
        self.client_id = os.getenv('GOOGLE_CLIENT_ID')
        self.client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
        self.admin_email = 'wayne79687968@gmail.com'  # 管理員 email
        
        if not self.client_id or not self.client_secret:
            logger.warning("Google OAuth 未完整配置")
    
    def get_google_provider_cfg(self):
        """獲取 Google OAuth 配置"""
        return requests.get("https://accounts.google.com/.well-known/openid_configuration").json()
    
    def create_or_update_user(self, google_id, email, name, picture):
        """創建或更新用戶資訊"""
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                now = datetime.now().isoformat()
                
                # 檢查用戶是否存在
                execute_query(cursor, "SELECT id, has_full_access FROM users WHERE email = ?", (email,))
                user = cursor.fetchone()
                
                # 判斷是否為管理員
                has_full_access = 1 if email == self.admin_email else 0
                
                if user:
                    # 更新現有用戶
                    execute_query(cursor, """
                        UPDATE users 
                        SET google_id = ?, name = ?, picture = ?, has_full_access = ?, updated_at = ?
                        WHERE email = ?
                    """, (google_id, name, picture, has_full_access, now, email))
                    user_id = user[0]
                else:
                    # 創建新用戶
                    execute_query(cursor, """
                        INSERT INTO users (email, google_id, name, picture, has_full_access, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (email, google_id, name, picture, has_full_access, now, now))
                    
                    # 獲取新創建的用戶 ID
                    execute_query(cursor, "SELECT id FROM users WHERE email = ?", (email,))
                    user_id = cursor.fetchone()[0]
                
                conn.commit()
                
                logger.info(f"用戶 {email} 已{'更新' if user else '創建'}，管理員權限: {bool(has_full_access)}")
                return {
                    'id': user_id,
                    'email': email,
                    'name': name,
                    'picture': picture,
                    'has_full_access': bool(has_full_access)
                }
                
        except Exception as e:
            logger.error(f"創建/更新用戶失敗: {e}")
            return None
    
    def get_user_by_email(self, email):
        """根據 email 獲取用戶資訊"""
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                execute_query(cursor, """
                    SELECT id, email, name, picture, has_full_access, created_at
                    FROM users WHERE email = ?
                """, (email,))
                
                user = cursor.fetchone()
                if user:
                    return {
                        'id': user[0],
                        'email': user[1],
                        'name': user[2],
                        'picture': user[3],
                        'has_full_access': bool(user[4]),
                        'created_at': user[5]
                    }
                return None
                
        except Exception as e:
            logger.error(f"獲取用戶資訊失敗: {e}")
            return None
    
    def verify_google_token(self, token):
        """驗證 Google ID Token"""
        try:
            idinfo = id_token.verify_oauth2_token(
                token, google_requests.Request(), self.client_id
            )
            
            if idinfo['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
                raise ValueError('Wrong issuer.')
            
            return {
                'google_id': idinfo['sub'],
                'email': idinfo['email'],
                'name': idinfo.get('name', ''),
                'picture': idinfo.get('picture', ''),
                'email_verified': idinfo.get('email_verified', False)
            }
            
        except ValueError as e:
            logger.error(f"Google token 驗證失敗: {e}")
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
    """完整權限裝飾器（目前只有 hotgame 相關功能開放給所有用戶）"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        
        user = session['user']
        if not user.get('has_full_access', False):
            return jsonify({'error': '此功能需要完整權限'}), 403
        
        return f(*args, **kwargs)
    return decorated_function

# 全域函數，用於模板中檢查權限
def has_full_access():
    """檢查當前用戶是否有完整權限"""
    if 'user' in session:
        return session['user'].get('has_full_access', False)
    return False

def get_current_user():
    """獲取當前用戶資訊"""
    return session.get('user')