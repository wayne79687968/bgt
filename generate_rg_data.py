#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 RG 推薦器所需的 JSONL 資料檔案
"""

import json
import logging
import os
from database import get_db_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8.8s [%(name)s:%(lineno)s] %(message)s"
)

logger = logging.getLogger(__name__)

def generate_games_jsonl():
    """從資料庫生成 bgg_GameItem.jl 檔案，如果沒有資料則生成測試資料"""
    logger.info("🎮 生成遊戲資料 JSONL 檔案...")
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 先檢查是否有真實資料
            cursor.execute("SELECT COUNT(*) FROM game_detail WHERE rating > 0")
            real_data_count = cursor.fetchone()[0]
            
            games_file = "data/bgg_GameItem.jl"
            count = 0
            
            if real_data_count > 0:
                logger.info(f"📊 發現 {real_data_count} 個真實遊戲資料")
                # 使用真實資料
                cursor.execute("""
                    SELECT 
                        objectid as bgg_id,
                        name,
                        year,
                        minplayers as min_players,
                        maxplayers as max_players,
                        minplaytime as min_time,
                        maxplaytime as max_time,
                        18 as min_age,
                        rating as avg_rating,
                        rank,
                        weight as complexity,
                        1000 as num_votes
                    FROM game_detail
                    WHERE rating > 0
                    ORDER BY rating DESC NULLS LAST
                    LIMIT 10000
                """)
                
                with open(games_file, 'w', encoding='utf-8') as f:
                    for row in cursor.fetchall():
                        game_data = {
                            'bgg_id': row[0],
                            'name': row[1] or 'Unknown',
                            'year': row[2] or 2000,
                            'min_players': row[3] or 1,
                            'max_players': row[4] or 4,
                            'min_time': row[5] or 30,
                            'max_time': row[6] or 120,
                            'min_age': row[7] or 8,
                            'avg_rating': float(row[8] or 0),
                            'rank': int(row[9]) if row[9] and row[9] > 0 else (count + 1),
                            'complexity': float(row[10] or 2.0),
                            'num_votes': int(row[11] or 1000),
                            'cooperative': False,
                            'compilation': False,
                            'compilation_of': [],
                            'implementation': [],
                            'integration': []
                        }
                        f.write(json.dumps(game_data, ensure_ascii=False) + '\n')
                        count += 1
            else:
                logger.warning("⚠️ 沒有真實遊戲資料，生成測試資料...")
                # 生成測試資料
                test_games = [
                    {'bgg_id': 174430, 'name': 'Gloomhaven', 'year': 2017, 'rating': 8.8, 'rank': 1, 'complexity': 3.9},
                    {'bgg_id': 161936, 'name': 'Pandemic Legacy: Season 1', 'year': 2015, 'rating': 8.6, 'rank': 2, 'complexity': 2.8},
                    {'bgg_id': 224517, 'name': 'Brass: Birmingham', 'year': 2018, 'rating': 8.7, 'rank': 3, 'complexity': 3.9},
                    {'bgg_id': 167791, 'name': 'Terraforming Mars', 'year': 2016, 'rating': 8.4, 'rank': 4, 'complexity': 3.2},
                    {'bgg_id': 182028, 'name': 'Through the Ages: A New Story of Civilization', 'year': 2015, 'rating': 8.6, 'rank': 5, 'complexity': 4.4},
                    {'bgg_id': 233398, 'name': 'Ark Nova', 'year': 2021, 'rating': 8.6, 'rank': 6, 'complexity': 3.7},
                    {'bgg_id': 220308, 'name': 'Gaia Project', 'year': 2017, 'rating': 8.4, 'rank': 7, 'complexity': 4.3},
                    {'bgg_id': 169786, 'name': 'Scythe', 'year': 2016, 'rating': 8.3, 'rank': 8, 'complexity': 3.4},
                    {'bgg_id': 266192, 'name': 'Wingspan', 'year': 2019, 'rating': 8.1, 'rank': 9, 'complexity': 2.4},
                    {'bgg_id': 115746, 'name': 'War of the Ring: Second Edition', 'year': 2012, 'rating': 8.4, 'rank': 10, 'complexity': 4.0}
                ]
                
                with open(games_file, 'w', encoding='utf-8') as f:
                    for game in test_games:
                        game_data = {
                            'bgg_id': game['bgg_id'],
                            'name': game['name'],
                            'year': game['year'],
                            'min_players': 1,
                            'max_players': 4,
                            'min_time': 60,
                            'max_time': 120,
                            'min_age': 12,
                            'avg_rating': game['rating'],
                            'rank': game['rank'],
                            'complexity': game['complexity'],
                            'num_votes': 5000,
                            'cooperative': False,
                            'compilation': False,
                            'compilation_of': [],
                            'implementation': [],
                            'integration': []
                        }
                        f.write(json.dumps(game_data, ensure_ascii=False) + '\n')
                        count += 1
            
            logger.info(f"✅ 遊戲資料檔案已生成: {games_file} ({count} 個遊戲)")
            return games_file
            
    except Exception as e:
        logger.error(f"生成遊戲資料失敗: {e}")
        return None

def generate_ratings_jsonl():
    """從資料庫生成 bgg_RatingItem.jl 檔案（合成評分資料）"""
    logger.info("⭐ 生成評分資料 JSONL 檔案...")
    
    try:
        # 生成測試評分資料
        test_game_ids = [174430, 161936, 224517, 167791, 182028, 233398, 220308, 169786, 266192, 115746]
        user_names = ['alice', 'bob', 'charlie', 'diana', 'edward', 'fiona', 'george', 'helen']
        
        ratings_file = "data/bgg_RatingItem.jl"
        count = 0
        
        with open(ratings_file, 'w', encoding='utf-8') as f:
            # 為每個測試遊戲生成多個用戶評分
            for game_id in test_game_ids:
                for i, user in enumerate(user_names):
                    # 生成不同的評分
                    base_rating = 7.0 + (i % 3)  # 7-9分之間
                    rating_data = {
                        'bgg_id': game_id,
                        'bgg_user_name': user,
                        'bgg_user_rating': base_rating
                    }
                    f.write(json.dumps(rating_data, ensure_ascii=False) + '\n')
                    count += 1
        
        logger.info(f"✅ 評分資料檔案已生成: {ratings_file} ({count} 個評分)")
        return ratings_file
            
    except Exception as e:
        logger.error(f"生成評分資料失敗: {e}")
        return None

def main():
    """主函數"""
    logger.info("🚀 開始生成 RG 推薦器資料檔案...")
    
    # 確保資料目錄存在
    os.makedirs("data", exist_ok=True)
    
    # 生成檔案
    games_file = generate_games_jsonl()
    ratings_file = generate_ratings_jsonl()
    
    if games_file and ratings_file:
        logger.info("🎉 所有資料檔案生成完成！")
        logger.info(f"遊戲資料: {games_file}")
        logger.info(f"評分資料: {ratings_file}")
    else:
        logger.error("❌ 資料檔案生成失敗")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())