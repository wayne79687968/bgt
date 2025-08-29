#!/usr/bin/env python3
"""
BGG 設計師/繪師追蹤系統
用於搜尋、追蹤和更新設計師/繪師的作品資訊
"""

import requests
import xml.etree.ElementTree as ET
import json
import time
import re
from datetime import datetime
from typing import List, Dict, Optional
from database import get_db_connection, get_database_config
import logging

logger = logging.getLogger(__name__)

class CreatorTracker:
    """設計師/繪師追蹤器"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'BGG-Creator-Tracker/1.0'
        })
        
    def search_creators(self, query: str, creator_type: str = 'boardgamedesigner') -> List[Dict]:
        """
        搜尋設計師或繪師
        
        Args:
            query: 搜尋關鍵字
            creator_type: 'boardgamedesigner' 或 'boardgameartist'
        
        Returns:
            List[Dict]: 搜尋結果
        """
        url = f"https://boardgamegeek.com/xmlapi2/search"
        params = {
            'query': query,
            'type': creator_type
        }
        
        try:
            logger.info(f"搜尋 {creator_type}: {query}")
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            root = ET.fromstring(response.content)
            results = []
            
            for item in root.findall('item'):
                creator_id = item.get('id')
                creator_name = item.find('name').get('value') if item.find('name') is not None else 'Unknown'
                
                results.append({
                    'id': int(creator_id),
                    'name': creator_name,
                    'type': creator_type
                })
                
            logger.info(f"找到 {len(results)} 個結果")
            return results
            
        except Exception as e:
            logger.error(f"搜尋失敗: {e}")
            return []
    
    def get_creator_details(self, creator_id: int, creator_type: str) -> Optional[Dict]:
        """
        獲取設計師/繪師的詳細資料
        
        Args:
            creator_id: 設計師/繪師 ID
            creator_type: 'designer' 或 'artist'
        
        Returns:
            Dict: 詳細資料，包含照片、描述、前5個作品
        """
        # 構建 BGG URL
        type_mapping = {
            'designer': 'boardgamedesigner',
            'artist': 'boardgameartist'
        }
        bgg_type = type_mapping.get(creator_type, 'boardgamedesigner')
        
        # 先獲取基本資料和 slug
        basic_info = self._get_creator_basic_info(creator_id, bgg_type)
        if not basic_info:
            return None
            
        # 獲取作品列表 (前5個，按平均分排序)
        games = self._get_creator_games(creator_id, basic_info['slug'], bgg_type, limit=5, sort='average')
        
        return {
            'id': creator_id,
            'name': basic_info['name'],
            'type': creator_type,
            'description': basic_info.get('description', ''),
            'image_url': basic_info.get('image_url', ''),
            'slug': basic_info['slug'],
            'top_games': games
        }
    
    def _get_creator_basic_info(self, creator_id: int, bgg_type: str) -> Optional[Dict]:
        """獲取設計師/繪師基本資訊"""
        try:
            # 嘗試從 BGG 頁面獲取基本資訊
            url = f"https://boardgamegeek.com/{bgg_type}/{creator_id}"
            response = self.session.get(url, timeout=30)
            
            if response.status_code != 200:
                logger.warning(f"無法獲取 {creator_id} 的基本資訊")
                return None
            
            html = response.text
            
            # 解析名稱
            name_match = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
            name = name_match.group(1).strip() if name_match else f'Creator {creator_id}'
            
            # 解析 slug (從 URL 中提取)
            slug_match = re.search(rf'/{bgg_type}/{creator_id}/([^/]+)', response.url)
            slug = slug_match.group(1) if slug_match else name.lower().replace(' ', '-')
            
            # 解析描述
            desc_match = re.search(r'<div class="game_description_body"[^>]*>([^<]+)</div>', html)
            description = desc_match.group(1).strip() if desc_match else ''
            
            # 解析頭像
            img_match = re.search(r'<img[^>]*src="([^"]*)"[^>]*class="[^"]*avatar[^"]*"', html)
            image_url = img_match.group(1) if img_match else ''
            
            return {
                'name': name,
                'slug': slug,
                'description': description,
                'image_url': image_url
            }
            
        except Exception as e:
            logger.error(f"獲取基本資訊失敗: {e}")
            return {'name': f'Creator {creator_id}', 'slug': f'creator-{creator_id}'}
    
    def _get_creator_games(self, creator_id: int, slug: str, bgg_type: str, 
                          limit: Optional[int] = None, sort: str = 'average') -> List[Dict]:
        """獲取設計師/繪師的遊戲作品"""
        try:
            url = f"https://boardgamegeek.com/{bgg_type}/{creator_id}/{slug}/linkeditems/{bgg_type}"
            params = {
                'pageid': 1,
                'sort': sort
            }
            
            response = self.session.get(url, params=params, timeout=30)
            if response.status_code != 200:
                logger.warning(f"無法獲取 {creator_id} 的作品列表")
                return []
            
            html = response.text
            games = []
            
            # 解析遊戲列表 (簡化版，實際需要更複雜的解析)
            # 這裡先返回模擬資料，實際實作時需要解析 HTML
            game_pattern = r'<td class="collection_objectname"[^>]*>.*?<a href="/boardgame/(\d+)/[^"]*">([^<]+)</a>'
            matches = re.findall(game_pattern, html, re.DOTALL)
            
            for i, (game_id, game_name) in enumerate(matches[:limit] if limit else matches):
                games.append({
                    'bgg_id': int(game_id),
                    'name': game_name.strip(),
                    'year': None,  # 需要進一步解析
                    'rating': None,  # 需要進一步解析
                    'rank': i + 1
                })
            
            return games
            
        except Exception as e:
            logger.error(f"獲取作品列表失敗: {e}")
            return []
    
    def get_all_creator_games(self, creator_id: int, slug: str, bgg_type: str, 
                             existing_games: List[int] = None) -> List[Dict]:
        """
        獲取設計師/繪師的所有作品 (用於追蹤時的完整同步)
        
        Args:
            creator_id: 設計師/繪師 ID
            slug: URL slug
            bgg_type: BGG 類型
            existing_games: 已存在的遊戲 ID 列表，用於增量更新
        
        Returns:
            List[Dict]: 所有遊戲作品
        """
        all_games = []
        page = 1
        existing_games = existing_games or []
        
        while True:
            try:
                url = f"https://boardgamegeek.com/{bgg_type}/{creator_id}/{slug}/linkeditems/{bgg_type}"
                params = {
                    'pageid': page,
                    'sort': 'yearpublished'  # 按年份排序，用於增量更新
                }
                
                response = self.session.get(url, params=params, timeout=30)
                if response.status_code != 200:
                    break
                
                html = response.text
                page_games = []
                
                # 解析當前頁面的遊戲
                # 實際實作時需要更詳細的 HTML 解析
                game_pattern = r'<td class="collection_objectname"[^>]*>.*?<a href="/boardgame/(\d+)/[^"]*">([^<]+)</a>'
                matches = re.findall(game_pattern, html, re.DOTALL)
                
                for game_id, game_name in matches:
                    game_id = int(game_id)
                    
                    # 如果遊戲已存在，停止增量更新
                    if game_id in existing_games:
                        logger.info(f"遇到已存在的遊戲 {game_id}，停止更新")
                        return all_games
                    
                    page_games.append({
                        'bgg_id': game_id,
                        'name': game_name.strip(),
                        'year': None,  # 需要進一步解析
                        'rating': None,
                        'rank': None
                    })
                
                if not page_games:
                    break
                    
                all_games.extend(page_games)
                page += 1
                time.sleep(1)  # 避免請求過於頻繁
                
            except Exception as e:
                logger.error(f"獲取第 {page} 頁作品失敗: {e}")
                break
        
        return all_games
    
    def save_creator_to_db(self, creator_data: Dict) -> int:
        """將設計師/繪師資料儲存到資料庫"""
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                now = datetime.now().isoformat()
                
                # 插入或更新設計師/繪師
                if get_database_config()['type'] == 'postgresql':
                    cursor.execute("""
                        INSERT INTO creators (bgg_id, name, type, description, image_url, slug, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (bgg_id) DO UPDATE SET
                            name = EXCLUDED.name,
                            description = EXCLUDED.description,
                            image_url = EXCLUDED.image_url,
                            slug = EXCLUDED.slug,
                            updated_at = EXCLUDED.updated_at
                        RETURNING id
                    """, (
                        creator_data['id'], creator_data['name'], creator_data['type'],
                        creator_data.get('description', ''), creator_data.get('image_url', ''),
                        creator_data.get('slug', ''), now, now
                    ))
                    creator_id = cursor.fetchone()[0]
                else:
                    # SQLite
                    cursor.execute("""
                        INSERT OR REPLACE INTO creators 
                        (bgg_id, name, type, description, image_url, slug, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        creator_data['id'], creator_data['name'], creator_data['type'],
                        creator_data.get('description', ''), creator_data.get('image_url', ''),
                        creator_data.get('slug', ''), now, now
                    ))
                    creator_id = cursor.lastrowid
                    
                    # 獲取實際的 creator_id
                    cursor.execute("SELECT id FROM creators WHERE bgg_id = ?", (creator_data['id'],))
                    result = cursor.fetchone()
                    creator_id = result[0] if result else creator_id
                
                logger.info(f"儲存設計師/繪師: {creator_data['name']} (ID: {creator_id})")
                return creator_id
                
        except Exception as e:
            logger.error(f"儲存設計師/繪師失敗: {e}")
            return None
    
    def save_creator_games(self, creator_id: int, games: List[Dict]):
        """儲存設計師/繪師的遊戲作品"""
        if not games:
            return
        
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                now = datetime.now().isoformat()
                
                for game in games:
                    if get_database_config()['type'] == 'postgresql':
                        cursor.execute("""
                            INSERT INTO creator_games 
                            (creator_id, bgg_game_id, game_name, year_published, rating, rank_position, created_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (creator_id, bgg_game_id) DO UPDATE SET
                                game_name = EXCLUDED.game_name,
                                year_published = EXCLUDED.year_published,
                                rating = EXCLUDED.rating,
                                rank_position = EXCLUDED.rank_position
                        """, (
                            creator_id, game['bgg_id'], game['name'],
                            game.get('year'), game.get('rating'), game.get('rank'), now
                        ))
                    else:
                        # SQLite
                        cursor.execute("""
                            INSERT OR REPLACE INTO creator_games
                            (creator_id, bgg_game_id, game_name, year_published, rating, rank_position, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (
                            creator_id, game['bgg_id'], game['name'],
                            game.get('year'), game.get('rating'), game.get('rank'), now
                        ))
                
                logger.info(f"儲存 {len(games)} 個遊戲作品")
                
        except Exception as e:
            logger.error(f"儲存遊戲作品失敗: {e}")

# 測試函數
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    tracker = CreatorTracker()
    
    # 測試搜尋
    results = tracker.search_creators("Vital Lacerda", "boardgamedesigner")
    print(f"搜尋結果: {results}")
    
    if results:
        # 測試獲取詳細資料
        details = tracker.get_creator_details(results[0]['id'], 'designer')
        print(f"詳細資料: {details}")