#!/usr/bin/env python3
"""
Email 通知服務
用於發送設計師/繪師新作品通知
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
import logging
from typing import List, Dict
import json

logger = logging.getLogger(__name__)

class EmailService:
    """Email 通知服務"""
    
    def __init__(self):
        self.smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
        self.smtp_port = int(os.getenv('SMTP_PORT', 587))
        self.smtp_username = os.getenv('SMTP_USERNAME', '')
        self.smtp_password = os.getenv('SMTP_PASSWORD', '')
        self.from_email = os.getenv('FROM_EMAIL', self.smtp_username)
        self.from_name = os.getenv('FROM_NAME', 'BGG 設計師追蹤')
        
        # 檢查必要配置
        if not all([self.smtp_username, self.smtp_password]):
            logger.warning("Email 服務未完整配置，將跳過實際發送")
    
    def send_new_game_notification(self, user_emails: List[str], creator_name: str, 
                                  creator_type: str, new_games: List[Dict]) -> bool:
        """
        發送新遊戲通知 email
        
        Args:
            user_emails: 收件人 email 列表
            creator_name: 設計師/繪師名稱
            creator_type: 'designer' 或 'artist'
            new_games: 新遊戲列表
        
        Returns:
            bool: 是否發送成功
        """
        if not user_emails or not new_games:
            return True
        
        if not all([self.smtp_username, self.smtp_password]):
            logger.info(f"Email 未配置，跳過發送通知給 {len(user_emails)} 位用戶")
            return True
        
        try:
            # 準備 email 內容
            subject = f"🎲 {creator_name} 有新作品發布！"
            
            type_name = "繪師" if creator_type == "artist" else "設計師"
            
            # HTML 內容
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <style>
                    body {{ font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                             color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                    .content {{ background: white; padding: 30px; border-radius: 0 0 10px 10px; 
                              box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
                    .creator-info {{ background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0; }}
                    .game-list {{ margin: 20px 0; }}
                    .game-item {{ background: #fff; border: 1px solid #e9ecef; border-radius: 6px; 
                                 padding: 15px; margin: 10px 0; }}
                    .game-name {{ font-weight: bold; color: #2c3e50; font-size: 16px; }}
                    .game-year {{ color: #6c757d; font-size: 14px; }}
                    .footer {{ text-align: center; margin-top: 30px; padding-top: 20px; 
                             border-top: 1px solid #e9ecef; color: #6c757d; }}
                    .unsubscribe {{ font-size: 12px; color: #6c757d; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>🎨 新作品通知</h1>
                        <p>您追蹤的{type_name}有新作品發布了！</p>
                    </div>
                    
                    <div class="content">
                        <div class="creator-info">
                            <h2>👤 {creator_name}</h2>
                            <p><strong>類型:</strong> {type_name}</p>
                            <p><strong>新作品數量:</strong> {len(new_games)} 個</p>
                        </div>
                        
                        <h3>📚 新作品列表</h3>
                        <div class="game-list">
            """
            
            # 添加遊戲列表
            for game in new_games:
                game_year = f" ({game.get('year', 'TBA')})" if game.get('year') else ""
                html_content += f"""
                    <div class="game-item">
                        <div class="game-name">{game['name']}{game_year}</div>
                        {f'<div class="game-year">發布年份: {game["year"]}</div>' if game.get('year') else ''}
                    </div>
                """
            
            html_content += f"""
                        </div>
                        
                        <div class="footer">
                            <p>感謝您使用 BGG 設計師追蹤服務！</p>
                            <p class="unsubscribe">
                                如不想再收到此類通知，請到設定頁面取消追蹤該{type_name}。
                            </p>
                        </div>
                    </div>
                </div>
            </body>
            </html>
            """
            
            # 文字版本內容
            text_content = f"""
            🎲 {creator_name} 新作品通知
            
            您追蹤的{type_name} {creator_name} 有 {len(new_games)} 個新作品發布：
            
            """
            
            for game in new_games:
                game_year = f" ({game.get('year', 'TBA')})" if game.get('year') else ""
                text_content += f"• {game['name']}{game_year}\n"
            
            text_content += f"""
            
            感謝您使用 BGG 設計師追蹤服務！
            如不想再收到此類通知，請到設定頁面取消追蹤該{type_name}。
            """
            
            # 發送給每個用戶
            success_count = 0
            for email in user_emails:
                if self._send_email(email, subject, text_content, html_content):
                    success_count += 1
            
            logger.info(f"成功發送 {success_count}/{len(user_emails)} 封通知 email")
            return success_count > 0
            
        except Exception as e:
            logger.error(f"發送通知 email 失敗: {e}")
            return False
    
    def _send_email(self, to_email: str, subject: str, text_content: str, html_content: str) -> bool:
        """發送單封 email"""
        try:
            # 建立訊息
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = formataddr((self.from_name, self.from_email))
            msg['To'] = to_email
            
            # 添加內容
            text_part = MIMEText(text_content, 'plain', 'utf-8')
            html_part = MIMEText(html_content, 'html', 'utf-8')
            
            msg.attach(text_part)
            msg.attach(html_part)
            
            # 發送
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_username, self.smtp_password)
                server.send_message(msg)
            
            logger.debug(f"成功發送 email 到 {to_email}")
            return True
            
        except Exception as e:
            logger.error(f"發送 email 到 {to_email} 失敗: {e}")
            return False
    
    def test_email_connection(self) -> bool:
        """測試 email 連線"""
        if not all([self.smtp_username, self.smtp_password]):
            logger.warning("Email 配置不完整")
            return False
        
        try:
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_username, self.smtp_password)
            
            logger.info("Email 連線測試成功")
            return True
            
        except Exception as e:
            logger.error(f"Email 連線測試失敗: {e}")
            return False

# 測試用
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    email_service = EmailService()
    
    # 測試連線
    if email_service.test_email_connection():
        print("✅ Email 服務配置正確")
    else:
        print("❌ Email 服務配置有問題")
    
    # 測試發送（如果有配置）
    test_games = [
        {'name': 'Test Game 1', 'year': 2024},
        {'name': 'Test Game 2', 'year': 2025}
    ]
    
    # 這裡只是測試，不會真的發送
    # email_service.send_new_game_notification(['test@example.com'], 'Test Designer', 'designer', test_games)