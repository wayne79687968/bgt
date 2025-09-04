#!/usr/bin/env python3
"""
生產環境資料初始化腳本
為 RG 推薦系統準備足夠的遊戲資料
"""

import json
import logging
import os
import sys
import requests
import xml.etree.ElementTree as ET
import time
from database import get_db_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8.8s [%(name)s:%(lineno)s] %(message)s"
)

logger = logging.getLogger(__name__)

def fetch_bgg_top_games(limit=200):
    """抓取 BGG 前 N 名熱門遊戲"""
    logger.info(f"🎯 準備抓取 BGG 前 {limit} 名遊戲...")
    
    games_to_fetch = []
    
    # BGG 熱門遊戲 ID（手動整理的熱門遊戲列表）
    popular_games = [
        174430, 161936, 224517, 167791, 182028, 233398, 220308, 169786, 266192, 115746,
        12333, 36218, 31260, 68448, 13, 822, 84876, 170216, 146021, 127023,
        233078, 251247, 2651, 21790, 173346, 148228, 40834, 102794, 139020, 18602,
        3076, 96913, 164928, 72125, 42, 171623, 132531, 124742, 1406, 28720,
        29208, 230802, 4098, 194655, 133570, 131961, 30549, 178900, 205637, 148949,
        143741, 32918, 37111, 172726, 150376, 183394, 124361, 170042, 195421, 209685,
        191189, 216132, 62219, 9209, 155426, 175914, 126163, 175155, 300531, 180263,
        148261, 181304, 202408, 35677, 6249, 178336, 156336, 172386, 84814, 246900,
        14996, 129622, 3955, 193738, 95789, 171131, 163412, 140934, 163967, 102680,
        52043, 4815, 164153, 1927, 146508, 5404, 28143, 54138, 154203, 172308
    ]
    
    for game_id in popular_games[:limit]:
        games_to_fetch.append(game_id)
    
    logger.info(f"📋 準備抓取 {len(games_to_fetch)} 個遊戲")
    return games_to_fetch

def fetch_and_save_game_details(game_ids):
    """批量抓取並儲存遊戲詳細資訊"""
    success_count = 0
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        for i, game_id in enumerate(game_ids):
            try:
                logger.info(f"🔍 抓取遊戲 {game_id} ({i+1}/{len(game_ids)})")
                
                # 檢查是否已存在
                cursor.execute('SELECT 1 FROM game_detail WHERE objectid = %s', (game_id,))
                if cursor.fetchone():
                    logger.info(f"⏭️ 遊戲 {game_id} 已存在，跳過")
                    continue
                
                # 從 BGG API 抓取
                url = 'https://boardgamegeek.com/xmlapi2/thing'
                params = {'id': game_id, 'stats': '1'}
                
                response = requests.get(url, params=params)
                response.raise_for_status()
                
                root = ET.fromstring(response.content)
                item = root.find('item')
                
                if item is None:
                    logger.warning(f"❌ 遊戲 {game_id} 無資料")
                    continue
                
                # 解析遊戲資料
                name = item.find('name[@type="primary"]')
                name = name.get('value') if name is not None else f'Game {game_id}'
                
                year = item.find('yearpublished')
                year = int(year.get('value')) if year is not None else None
                
                stats = item.find('statistics/ratings')
                rating = None
                rank = None
                weight = None
                
                if stats is not None:
                    rating_elem = stats.find('average')
                    rating = float(rating_elem.get('value')) if rating_elem is not None else None
                    
                    rank_elem = stats.find('ranks/rank[@name="boardgame"]')
                    rank = int(rank_elem.get('value')) if rank_elem is not None and rank_elem.get('value').isdigit() else None
                    
                    weight_elem = stats.find('averageweight')
                    weight = float(weight_elem.get('value')) if weight_elem is not None else None
                
                minplayers = item.find('minplayers')
                minplayers = int(minplayers.get('value')) if minplayers is not None else None
                
                maxplayers = item.find('maxplayers')
                maxplayers = int(maxplayers.get('value')) if maxplayers is not None else None
                
                minplaytime = item.find('minplaytime')
                minplaytime = int(minplaytime.get('value')) if minplaytime is not None else None
                
                maxplaytime = item.find('maxplaytime')
                maxplaytime = int(maxplaytime.get('value')) if maxplaytime is not None else None
                
                categories = [link.get('value') for link in item.findall('link[@type="boardgamecategory"]')]
                mechanics = [link.get('value') for link in item.findall('link[@type="boardgamemechanic"]')]
                designers = [link.get('value') for link in item.findall('link[@type="boardgamedesigner"]')]
                artists = [link.get('value') for link in item.findall('link[@type="boardgameartist"]')]
                publishers = [link.get('value') for link in item.findall('link[@type="boardgamepublisher"]')]
                
                image = item.find('image')
                image = image.text if image is not None else None
                
                # 儲存到資料庫
                cursor.execute('''
                    INSERT INTO game_detail (
                        objectid, name, year, rating, rank, weight, 
                        minplayers, maxplayers, minplaytime, maxplaytime,
                        categories, mechanics, designers, artists, publishers, 
                        image, last_updated
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (objectid) DO UPDATE SET
                        name = EXCLUDED.name,
                        year = EXCLUDED.year,
                        rating = EXCLUDED.rating,
                        rank = EXCLUDED.rank,
                        weight = EXCLUDED.weight,
                        minplayers = EXCLUDED.minplayers,
                        maxplayers = EXCLUDED.maxplayers,
                        minplaytime = EXCLUDED.minplaytime,
                        maxplaytime = EXCLUDED.maxplaytime,
                        categories = EXCLUDED.categories,
                        mechanics = EXCLUDED.mechanics,
                        designers = EXCLUDED.designers,
                        artists = EXCLUDED.artists,
                        publishers = EXCLUDED.publishers,
                        image = EXCLUDED.image,
                        last_updated = NOW()
                ''', (
                    game_id, name, year, rating, rank, weight,
                    minplayers, maxplayers, minplaytime, maxplaytime,
                    json.dumps(categories), json.dumps(mechanics),
                    json.dumps(designers), json.dumps(artists),
                    json.dumps(publishers), image
                ))
                
                conn.commit()
                success_count += 1
                logger.info(f"✅ 成功儲存: {name} ({year})")
                
                # 避免被 BGG 限制
                time.sleep(1.5)
                
            except Exception as e:
                logger.error(f"❌ 抓取遊戲 {game_id} 失敗: {e}")
                continue
    
    logger.info(f"🎉 成功抓取並儲存了 {success_count} 個遊戲")
    return success_count

def main():
    """主函數"""
    logger.info("🚀 開始生產環境資料初始化...")
    
    # 檢查現有資料量
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM game_detail WHERE rating > 0")
            existing_count = cursor.fetchone()[0]
            
        logger.info(f"📊 現有遊戲資料: {existing_count} 個")
        
        # 如果資料不足，開始抓取
        if existing_count < 100:
            logger.info("⚠️ 資料不足，開始抓取 BGG 熱門遊戲...")
            
            # 抓取遊戲 ID
            game_ids = fetch_bgg_top_games(150)  # 抓取前 150 名
            
            # 批量抓取並儲存
            success_count = fetch_and_save_game_details(game_ids)
            
            logger.info(f"✅ 資料初始化完成，新增 {success_count} 個遊戲")
            
            # 重新生成 RG 資料檔案
            from generate_rg_data import generate_games_jsonl, generate_ratings_jsonl
            
            logger.info("📋 重新生成 RG 資料檔案...")
            generate_games_jsonl()
            generate_ratings_jsonl()
            
        else:
            logger.info("✅ 資料充足，無需初始化")
            
    except Exception as e:
        logger.error(f"❌ 生產環境資料初始化失敗: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()