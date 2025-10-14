#!/usr/bin/env python3
"""
BGG Scraper 資料提取器
使用 board-game-scraper 直接從 BGG 抓取用戶收藏資料
"""

import json
import os
import logging
import requests
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional
import time
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

class BGGScraperExtractor:
    """使用 BGG XML API 抓取用戶收藏和遊戲資料"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'BGG-RAG-Daily/1.0 (https://github.com/your-repo)'
        })
        
    def fetch_user_collection(self, username: str, max_retries: int = 3) -> Optional[List[Dict]]:
        """抓取用戶收藏資料"""
        base_url = "https://boardgamegeek.com/xmlapi2/collection"
        params = {
            'username': username,
            'subtype': 'boardgame',
            'excludesubtype': 'boardgameexpansion',
            'stats': '1',
            'version': '0'
        }
        
        url = f"{base_url}?{urlencode(params)}"
        
        for attempt in range(max_retries):
            try:
                logger.info(f"抓取用戶 {username} 的收藏資料 (嘗試 {attempt + 1}/{max_retries})")
                response = self.session.get(url, timeout=30)
                
                if response.status_code == 202:
                    # BGG 返回 202，需要等待重試
                    wait_time = min(2 ** attempt, 10)  # 指數退避，最長10秒
                    logger.info(f"BGG 回傳 202，等待 {wait_time} 秒後重試...")
                    time.sleep(wait_time)
                    continue
                    
                if response.status_code == 200:
                    return self._parse_collection_xml(response.content, username)
                    
                logger.error(f"HTTP 錯誤 {response.status_code}: {response.text}")
                return None
                
            except Exception as e:
                logger.error(f"抓取用戶收藏時發生錯誤 (嘗試 {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2)
                    
        logger.error(f"抓取用戶 {username} 收藏資料失敗")
        return None
    
    def _parse_collection_xml(self, xml_content: bytes, username: str) -> List[Dict]:
        """解析 BGG collection XML"""
        try:
            root = ET.fromstring(xml_content)
            collection_items = []
            
            for item in root.findall('.//item'):
                game_id = item.get('objectid')
                if not game_id:
                    continue
                    
                # 基本資訊
                name_elem = item.find('name')
                game_name = name_elem.text if name_elem is not None else ""
                
                year_elem = item.find('yearpublished')
                year = int(year_elem.text) if year_elem is not None and year_elem.text else None
                
                # 收藏狀態
                status = item.find('status')
                own = status.get('own', '0') == '1' if status is not None else False
                want = status.get('want', '0') == '1' if status is not None else False
                wishlist = status.get('wishlist', '0') == '1' if status is not None else False
                
                # 用戶評分
                rating_elem = item.find('.//rating')
                user_rating = None
                if rating_elem is not None and rating_elem.get('value') not in [None, 'N/A']:
                    try:
                        user_rating = float(rating_elem.get('value'))
                    except (ValueError, TypeError):
                        user_rating = None
                
                # 統計資料
                stats = item.find('stats')
                bgg_rating = None
                bgg_rank = None
                if stats is not None:
                    rating_elem = stats.find('.//average')
                    if rating_elem is not None:
                        try:
                            bgg_rating = float(rating_elem.get('value', 0))
                        except (ValueError, TypeError):
                            pass
                            
                    rank_elem = stats.find('.//rank[@type="subtype"]')
                    if rank_elem is not None and rank_elem.get('value') not in [None, 'Not Ranked']:
                        try:
                            bgg_rank = int(rank_elem.get('value'))
                        except (ValueError, TypeError):
                            pass
                
                collection_items.append({
                    'user_id': f'user_{username}',
                    'game_id': game_id,
                    'game_name': game_name,
                    'year': year,
                    'own': own,
                    'want': want,
                    'wishlist': wishlist,
                    'user_rating': user_rating,
                    'bgg_rating': bgg_rating,
                    'bgg_rank': bgg_rank
                })
                
            logger.info(f"解析了用戶 {username} 的 {len(collection_items)} 個收藏項目")
            return collection_items
            
        except ET.ParseError as e:
            logger.error(f"XML 解析錯誤: {e}")
            return []
        except Exception as e:
            logger.error(f"解析收藏 XML 時發生錯誤: {e}")
            return []
    
    def fetch_game_details(self, game_ids: List[str], batch_size: int = 50) -> Dict[str, Dict]:
        """批量抓取遊戲詳細資料"""
        game_details = {}
        
        # 分批處理遊戲ID
        for i in range(0, len(game_ids), batch_size):
            batch_ids = game_ids[i:i + batch_size]
            batch_details = self._fetch_game_batch(batch_ids)
            game_details.update(batch_details)
            
            # 避免過度請求
            if i + batch_size < len(game_ids):
                time.sleep(1)
                
        return game_details
    
    def _fetch_game_batch(self, game_ids: List[str]) -> Dict[str, Dict]:
        """抓取一批遊戲的詳細資料"""
        base_url = "https://boardgamegeek.com/xmlapi2/thing"
        params = {
            'id': ','.join(game_ids),
            'stats': '1'
        }
        
        url = f"{base_url}?{urlencode(params)}"
        
        try:
            logger.info(f"抓取 {len(game_ids)} 個遊戲的詳細資料")
            response = self.session.get(url, timeout=30)
            
            if response.status_code == 200:
                return self._parse_games_xml(response.content)
            else:
                logger.error(f"抓取遊戲詳細資料失敗: HTTP {response.status_code}")
                return {}
                
        except Exception as e:
            logger.error(f"抓取遊戲詳細資料時發生錯誤: {e}")
            return {}
    
    def _parse_games_xml(self, xml_content: bytes) -> Dict[str, Dict]:
        """解析遊戲詳細資料 XML"""
        try:
            root = ET.fromstring(xml_content)
            games = {}
            
            for item in root.findall('.//item'):
                game_id = item.get('id')
                if not game_id:
                    continue
                
                # 基本資訊
                name_elem = item.find('.//name[@type="primary"]')
                if name_elem is None:
                    name_elem = item.find('.//name')
                game_name = name_elem.get('value', '') if name_elem is not None else ''
                
                year_elem = item.find('yearpublished')
                year = int(year_elem.get('value')) if year_elem is not None and year_elem.get('value') else None
                
                # 玩家數量和時間
                minplayers_elem = item.find('minplayers')
                maxplayers_elem = item.find('maxplayers')
                playingtime_elem = item.find('playingtime')
                
                minplayers = int(minplayers_elem.get('value', 1)) if minplayers_elem is not None else 1
                maxplayers = int(maxplayers_elem.get('value', 1)) if maxplayers_elem is not None else 1
                playing_time = int(playingtime_elem.get('value', 0)) if playingtime_elem is not None else 0
                
                # 複雜度和評分
                stats = item.find('statistics/ratings')
                rating = None
                complexity = None
                rank = None
                
                if stats is not None:
                    average_elem = stats.find('average')
                    if average_elem is not None:
                        try:
                            rating = float(average_elem.get('value', 0))
                        except (ValueError, TypeError):
                            pass
                    
                    weight_elem = stats.find('averageweight')
                    if weight_elem is not None:
                        try:
                            complexity = float(weight_elem.get('value', 0))
                        except (ValueError, TypeError):
                            pass
                    
                    rank_elem = stats.find('.//rank[@name="boardgame"]')
                    if rank_elem is not None and rank_elem.get('value') not in [None, 'Not Ranked']:
                        try:
                            rank = int(rank_elem.get('value'))
                        except (ValueError, TypeError):
                            pass
                
                games[game_id] = {
                    'id': game_id,
                    'name': game_name,
                    'year': year,
                    'min_players': minplayers,
                    'max_players': maxplayers,
                    'playing_time': playing_time,
                    'min_age': 0,  # BGG XML 不總是包含年齡資訊
                    'complexity': complexity or 0.0,
                    'bgg_rank': rank or 0,
                    'rating': rating or 0.0,
                    'weight': complexity or 0.0,
                    'description': ''  # 詳細描述需要額外請求
                }
                
            logger.info(f"解析了 {len(games)} 個遊戲的詳細資料")
            return games
            
        except ET.ParseError as e:
            logger.error(f"遊戲 XML 解析錯誤: {e}")
            return {}
        except Exception as e:
            logger.error(f"解析遊戲 XML 時發生錯誤: {e}")
            return {}
    
    def export_to_jsonl(self, username: str, output_dir: str = 'data') -> bool:
        """抓取用戶資料並輸出為 JSONL 格式"""
        try:
            # 動態選擇最佳可用的資料目錄
            possible_dirs = ['/app/data', 'data', '/tmp/data']
            best_dir = output_dir
            
            if output_dir == 'data':
                for data_dir in possible_dirs:
                    if os.path.exists(data_dir) and os.access(data_dir, os.W_OK):
                        best_dir = data_dir
                        logger.info(f"📁 使用資料目錄: {best_dir}")
                        break
            
            # 創建用戶特定的輸出目錄
            user_dir = os.path.join(best_dir, 'rg_users', username)
            os.makedirs(user_dir, exist_ok=True)
            
            # 抓取用戶收藏
            collection = self.fetch_user_collection(username)
            if not collection:
                logger.error(f"無法抓取用戶 {username} 的收藏資料")
                return False
            
            # 從收藏資料生成簡化的遊戲資料（如果 BGG API 限制太嚴格）
            games_file = os.path.join(user_dir, 'bgg_GameItem.jl')
            with open(games_file, 'w', encoding='utf-8') as f:
                processed_games = set()
                for item in collection:
                    game_id = item['game_id']
                    if game_id in processed_games:
                        continue
                    processed_games.add(game_id)
                    
                    # 使用收藏資料中的遊戲資訊創建基本遊戲資料
                    # 格式要符合 board-game-recommender 的要求
                    game_data = {
                        'bgg_id': int(game_id),
                        'name': item['game_name'] or f'Game {game_id}',
                        'year': item['year'] or 0,
                        'min_players': 1,  # 預設值
                        'max_players': 6,  # 預設值
                        'min_time': 60,  # 預設值
                        'max_time': 120,  # 預設值
                        'min_age': 0,
                        'avg_rating': item['bgg_rating'] or 0.0,
                        'rank': item['bgg_rank'] or 0,
                        'complexity': 2.5,  # 預設值
                        'num_votes': 100,  # 預設值
                        'cooperative': False,  # 預設值
                        'compilation': False,  # 預設值
                        'compilation_of': [],  # 預設值
                        'implementation': [],  # 預設值
                        'integration': []  # 預設值
                    }
                    f.write(json.dumps(game_data, ensure_ascii=False) + '\n')
            
            # 生成 RatingItem.jl
            ratings_file = os.path.join(user_dir, 'bgg_RatingItem.jl')
            with open(ratings_file, 'w', encoding='utf-8') as f:
                for item in collection:
                    # 計算評分（如果用戶沒有評分，根據收藏狀態推算）
                    rating = item['user_rating']
                    if rating is None:
                        if item['own']:
                            rating = 7.0
                        elif item['want'] or item['wishlist']:
                            rating = 6.0
                        else:
                            rating = 5.0
                    
                    rating_item = {
                        'bgg_id': int(item['game_id']),
                        'bgg_user_name': username,
                        'bgg_user_rating': rating
                    }
                    f.write(json.dumps(rating_item, ensure_ascii=False) + '\n')
            
            logger.info(f"成功為用戶 {username} 生成了 JSONL 檔案")
            logger.info(f"遊戲檔案: {games_file} ({len(processed_games)} 個遊戲)")
            logger.info(f"評分檔案: {ratings_file} ({len(collection)} 個評分)")
            
            return True
            
        except Exception as e:
            logger.error(f"導出 JSONL 檔案時發生錯誤: {e}")
            import traceback
            logger.error(f"詳細錯誤: {traceback.format_exc()}")
            return False

if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO)
    
    if len(sys.argv) < 2:
        print("使用方式: python3 bgg_scraper_extractor.py <username>")
        sys.exit(1)
    
    username = sys.argv[1]
    extractor = BGGScraperExtractor()
    success = extractor.export_to_jsonl(username)
    
    if success:
        print(f"✅ 成功為用戶 {username} 生成 JSONL 檔案")
    else:
        print(f"❌ 為用戶 {username} 生成 JSONL 檔案失敗")
        sys.exit(1)