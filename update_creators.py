#!/usr/bin/env python3
"""
設計師/繪師作品更新腳本
用於定期檢查追蹤的設計師/繪師是否有新作品
"""

import sys
import logging
from datetime import datetime
from creator_tracker import CreatorTracker
from database import get_db_connection
import json

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def get_followed_creators():
    """獲取所有被追蹤的設計師/繪師"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT c.id, c.bgg_id, c.name, c.type, c.slug
                FROM creators c
                JOIN user_follows uf ON c.id = uf.creator_id
            """)
            
            creators = []
            for row in cursor.fetchall():
                creators.append({
                    'id': row[0],
                    'bgg_id': row[1],
                    'name': row[2],
                    'type': row[3],
                    'slug': row[4]
                })
            
            return creators
            
    except Exception as e:
        logger.error(f"獲取追蹤設計師失敗: {e}")
        return []

def get_existing_games(creator_id):
    """獲取設計師/繪師現有的遊戲列表"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT bgg_game_id FROM creator_games 
                WHERE creator_id = ?
            """, (creator_id,))
            
            return [row[0] for row in cursor.fetchall()]
            
    except Exception as e:
        logger.error(f"獲取現有遊戲失敗: {e}")
        return []

def save_new_games(creator_id, new_games):
    """儲存新遊戲並記錄通知"""
    if not new_games:
        return []
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 獲取追蹤此設計師的用戶列表
            cursor.execute("""
                SELECT user_email FROM user_follows 
                WHERE creator_id = ?
            """, (creator_id,))
            
            user_emails = [row[0] for row in cursor.fetchall()]
            
            # 儲存新遊戲並建立通知記錄
            notifications = []
            now = datetime.now().isoformat()
            
            for game in new_games:
                # 儲存遊戲
                cursor.execute("""
                    INSERT OR REPLACE INTO creator_games
                    (creator_id, bgg_game_id, game_name, year_published, rating, rank_position, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    creator_id, game['bgg_id'], game['name'],
                    game.get('year'), game.get('rating'), game.get('rank'), now
                ))
                
                # 建立通知記錄
                cursor.execute("""
                    INSERT INTO game_notifications
                    (creator_id, bgg_game_id, game_name, year_published, notified_users, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    creator_id, game['bgg_id'], game['name'],
                    game.get('year'), json.dumps(user_emails), now
                ))
                
                notifications.append({
                    'game': game,
                    'users': user_emails
                })
            
            logger.info(f"儲存 {len(new_games)} 個新遊戲，需通知 {len(user_emails)} 位用戶")
            return notifications
            
    except Exception as e:
        logger.error(f"儲存新遊戲失敗: {e}")
        return []

def send_notification_emails(creator_name, creator_type, notifications):
    """發送新遊戲通知 email"""
    if not notifications:
        return
    
    try:
        from email_service import EmailService
        email_service = EmailService()
        
        # 收集所有需要通知的用戶
        all_users = set()
        all_games = []
        
        for notification in notifications:
            all_users.update(notification['users'])
            all_games.append(notification['game'])
        
        # 發送通知
        if all_users and all_games:
            logger.info(f"發送通知給 {len(all_users)} 位用戶，關於 {creator_name} 的 {len(all_games)} 個新作品")
            
            success = email_service.send_new_game_notification(
                list(all_users), creator_name, creator_type, all_games
            )
            
            if success:
                logger.info("Email 通知發送成功")
            else:
                logger.warning("Email 通知發送失敗")
        
        # 更新通知記錄為已發送
        with get_db_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            
            for notification in notifications:
                cursor.execute("""
                    UPDATE game_notifications 
                    SET sent_at = ? 
                    WHERE creator_id = ? AND bgg_game_id = ? AND sent_at IS NULL
                """, (now, notification['creator_id'], notification['game']['bgg_id']))
                
    except Exception as e:
        logger.error(f"發送通知失敗: {e}")

def update_creator_games(creator_data, tracker):
    """更新單個設計師/繪師的作品"""
    creator_id = creator_data['id']
    creator_name = creator_data['name']
    
    logger.info(f"更新設計師/繪師: {creator_name}")
    
    # 獲取現有遊戲列表
    existing_games = get_existing_games(creator_id)
    logger.info(f"{creator_name} 現有 {len(existing_games)} 個作品")
    
    # 獲取最新作品列表（按年份排序，增量更新）
    bgg_type = 'boardgamedesigner' if creator_data['type'] == 'designer' else 'boardgameartist'
    new_games = tracker.get_all_creator_games(
        creator_data['bgg_id'], 
        creator_data['slug'], 
        bgg_type,
        existing_games  # 傳入現有遊戲列表用於增量更新
    )
    
    if new_games:
        logger.info(f"{creator_name} 發現 {len(new_games)} 個新作品")
        
        # 儲存新遊戲並建立通知
        notifications = save_new_games(creator_id, new_games)
        
        # 發送通知 email
        if notifications:
            send_notification_emails(creator_name, creator_data['type'], notifications)
    else:
        logger.info(f"{creator_name} 沒有新作品")

def main():
    """主函數"""
    logger.info("開始更新設計師/繪師作品...")
    
    try:
        # 初始化追蹤器
        tracker = CreatorTracker()
        
        # 獲取所有被追蹤的設計師/繪師
        creators = get_followed_creators()
        logger.info(f"找到 {len(creators)} 個被追蹤的設計師/繪師")
        
        if not creators:
            logger.info("沒有需要更新的設計師/繪師")
            return
        
        # 逐個更新
        for creator in creators:
            try:
                update_creator_games(creator, tracker)
            except Exception as e:
                logger.error(f"更新 {creator['name']} 失敗: {e}")
                continue
        
        logger.info("設計師/繪師作品更新完成")
        
    except Exception as e:
        logger.error(f"更新過程發生錯誤: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()