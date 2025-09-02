#!/usr/bin/env python3
"""
BGG 資料提取器
從現有資料庫中提取遊戲和評分資料，轉換為推薦系統所需的格式
"""

import json
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class BGGDataExtractor:
    def __init__(self, db_path=None):
        # 總是使用統一的資料庫連接方法
        self.db_path = db_path  # 保留用於向後相容
        from database import get_database_config
        self.db_config = get_database_config()
        logger.info(f"資料庫配置: {self.db_config['type']}")
        
    def extract_games_data(self, output_file='data/bgg_GameItem.jl'):
        """從資料庫提取遊戲資料並輸出為 JSONL 格式"""
        try:
            # 使用統一的資料庫連接方法
            from database import get_db_connection
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # 查詢遊戲詳細資料
                query = """
                SELECT 
                    objectid,
                    name,
                    year,
                    minplayers,
                    maxplayers,
                    minplaytime,
                    0 as min_age,
                    weight,
                    rank,
                    rating,
                    weight,
                    '' as description
                FROM game_detail 
                WHERE objectid IS NOT NULL
                ORDER BY objectid
                """
                
                cursor.execute(query)
                games = cursor.fetchall()
                
                # 確保輸出目錄存在
                os.makedirs(os.path.dirname(output_file), exist_ok=True)
                
                # 寫入 JSONL 格式
                with open(output_file, 'w', encoding='utf-8') as f:
                    for game in games:
                        game_data = {
                            'id': str(game[0]),
                            'name': game[1] or '',
                            'year': game[2] or 0,
                            'min_players': game[3] or 1,
                            'max_players': game[4] or 1,
                            'playing_time': game[5] or 0,
                            'min_age': game[6] or 0,
                            'complexity': game[7] or 0.0,
                            'bgg_rank': game[8] or 0,
                            'rating': game[9] or 0.0,
                            'weight': game[10] or 0.0,
                            'description': game[11] or ''
                        }
                        f.write(json.dumps(game_data, ensure_ascii=False) + '\n')
                
                logger.info(f"提取了 {len(games)} 個遊戲資料到 {output_file}")
                return len(games)
            
        except Exception as e:
            logger.error(f"提取遊戲資料時發生錯誤: {e}")
            import traceback
            logger.error(f"詳細錯誤: {traceback.format_exc()}")
            return 0
    
    def extract_ratings_data(self, output_file='data/bgg_RatingItem.jl'):
        """從資料庫提取評分資料並輸出為 JSONL 格式"""
        try:
            from database import get_db_connection
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # 查詢用戶收藏和評分資料（只包含在 game_detail 中有資料的遊戲）
                query = """
                SELECT 
                    'user_' || c.objectid as username,
                    c.objectid,
                    COALESCE(c.rating, 0) as rating,
                    CASE WHEN c.status LIKE '%Own%' THEN 1 ELSE 0 END as owned,
                    CASE WHEN c.status LIKE '%Want%' THEN 1 ELSE 0 END as want_to_play,
                    0 as want_to_buy
                FROM collection c
                INNER JOIN game_detail g ON c.objectid = g.objectid
                WHERE c.objectid IS NOT NULL
                ORDER BY c.objectid
                """
                
                cursor.execute(query)
                ratings = cursor.fetchall()
                
                # 確保輸出目錄存在
                os.makedirs(os.path.dirname(output_file), exist_ok=True)
                
                # 寫入 JSONL 格式
                with open(output_file, 'w', encoding='utf-8') as f:
                    for rating in ratings:
                        # 生成評分（如果沒有明確評分，根據收藏狀態推算）
                        user_rating = rating[2]
                        if user_rating is None or user_rating == 0:
                            # 根據收藏狀態推算評分
                            if rating[3]:  # owned
                                user_rating = 7.0
                            elif rating[4]:  # want_to_play
                                user_rating = 6.0
                            elif rating[5]:  # want_to_buy
                                user_rating = 6.5
                            else:
                                user_rating = 5.0
                        
                        rating_data = {
                            'user_id': rating[0],
                            'game_id': str(rating[1]),
                            'rating': float(user_rating)
                        }
                        f.write(json.dumps(rating_data, ensure_ascii=False) + '\n')
                
                logger.info(f"提取了 {len(ratings)} 個評分資料到 {output_file}")
                return len(ratings)
            
        except Exception as e:
            logger.error(f"提取評分資料時發生錯誤: {e}")
            return 0
    
    def check_database_status(self):
        """檢查資料庫狀態"""
        try:
            from database import get_db_connection, get_database_config
            config = get_database_config()
            
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # 檢查資料表是否存在
                cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                    
                tables = [row[0] for row in cursor.fetchall()]
                logger.info(f"資料庫中的表: {tables}")
                
                if 'game_detail' in tables:
                    cursor.execute("SELECT COUNT(*) FROM game_detail")
                    game_count = cursor.fetchone()[0]
                    logger.info(f"game_detail 表中有 {game_count} 筆資料")
                else:
                    logger.error("game_detail 表不存在")
                    
                if 'collection' in tables:
                    cursor.execute("SELECT COUNT(*) FROM collection")
                    collection_count = cursor.fetchone()[0]
                    logger.info(f"collection 表中有 {collection_count} 筆資料")
                else:
                    logger.error("collection 表不存在")
                    
                return True
            
        except Exception as e:
            logger.error(f"檢查資料庫狀態時發生錯誤: {e}")
            import traceback
            logger.error(f"詳細錯誤: {traceback.format_exc()}")
            return False
    
    def extract_all_data(self):
        """提取所有推薦系統需要的資料"""
        logger.info(f"開始提取資料，資料庫路徑: {self.db_path}")
        
        # 檢查資料庫狀態
        if not self.check_database_status():
            logger.error("資料庫狀態檢查失敗")
            return False
        
        games_count = self.extract_games_data()
        ratings_count = self.extract_ratings_data()
        
        logger.info(f"資料提取完成：{games_count} 個遊戲，{ratings_count} 個評分")
        
        if games_count == 0:
            logger.error("沒有提取到遊戲資料")
            return False
            
        if ratings_count == 0:
            logger.warning("沒有提取到評分資料，推薦系統功能將受限")
            
        return games_count > 0

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    extractor = BGGDataExtractor()
    success = extractor.extract_all_data()
    print(f"資料提取{'成功' if success else '失敗'}")