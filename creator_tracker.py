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
from bs4 import BeautifulSoup
import urllib.parse

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
                
                # 獲取設計師的基本資料（包含照片）
                basic_details = self.get_creator_details(int(creator_id), creator_type)
                image_url = basic_details.get('image_url') if basic_details else None
                
                # 獲取 average 排序的第一筆遊戲
                top_game = None
                try:
                    # 確定正確的 API 類型
                    api_type = 'boardgamedesigner' if creator_type in ['designer', 'boardgamedesigner'] else 'boardgameartist'
                    slug = basic_details.get('slug') if basic_details else None
                    
                    if slug:
                        games = self.get_all_creator_games(int(creator_id), slug, api_type, sort='average', limit=1)
                        if games:
                            game = games[0]
                            top_game = {
                                'name': game.get('name'),
                                'url': f"https://boardgamegeek.com/boardgame/{game.get('id')}"
                            }
                except Exception as e:
                    logger.warning(f"無法獲取 {creator_name} 的 top game: {e}")
                
                results.append({
                    'id': int(creator_id),
                    'name': creator_name,
                    'type': creator_type,
                    'image_url': image_url,
                    'top_game': top_game
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
        games = self._get_creator_games(creator_id, basic_info['slug'], bgg_type, basic_info['name'], limit=5, sort='average')
        
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
            # 從 linkeditems 頁面獲取完整資訊
            url = f"https://boardgamegeek.com/{bgg_type}/{creator_id}/linkeditems/{bgg_type}?pageid=1&sort=average"
            response = self.session.get(url, timeout=30)
            
            if response.status_code != 200:
                logger.warning(f"無法獲取 {creator_id} 的基本資訊")
                return None
            
            html = response.text
            logger.debug(f"HTML length: {len(html)}")
            
            # 解析名稱 - 更寬鬆的模式
            name = f'Creator {creator_id}'  # 預設值
            
            # 嘗試多種名稱解析模式
            name_patterns = [
                r'<h1[^>]*class="[^"]*hero_name[^"]*"[^>]*>([^<]+)</h1>',
                r'<h1[^>]*>([^<]+)</h1>',
                r'<title>([^|]+)\s*\|',
                r'name="twitter:title"\s+content="([^"]+)"',
                r'"name":"([^"]+)"'
            ]
            
            for pattern in name_patterns:
                name_match = re.search(pattern, html, re.IGNORECASE)
                if name_match:
                    name = name_match.group(1).strip()
                    break
            
            logger.info(f"解析到名稱: {name}")
            
            # 解析 slug (從 URL 中提取)
            slug_match = re.search(rf'/{bgg_type}/{creator_id}/([^/?]+)', response.url)
            slug = slug_match.group(1) if slug_match else name.lower().replace(' ', '-').replace('.', '')
            
            # 嘗試從 JavaScript 物件中提取詳細資料
            description = ''
            image_url = ''
            
            # 尋找 GEEK.geekitemPreload JavaScript 物件
            js_match = re.search(r'GEEK\.geekitemPreload\s*=\s*({.+?});', html, re.DOTALL)
            if js_match:
                try:
                    import json
                    js_data = json.loads(js_match.group(1))
                    
                    # 提取描述
                    if 'item' in js_data and 'description' in js_data['item']:
                        desc_html = js_data['item']['description']
                        if desc_html:
                            # 使用 BeautifulSoup 清理 HTML 標籤
                            from bs4 import BeautifulSoup
                            desc_soup = BeautifulSoup(desc_html, 'html.parser')
                            description = desc_soup.get_text(separator=' ', strip=True)
                            logger.info(f"從 JS 資料解析到描述: {len(description)} 字元")
                    
                    # 圖片將使用 Images API 獲取，不從頁面解析
                
                except Exception as e:
                    logger.warning(f"解析 JavaScript 資料失敗: {e}")
                    # 列印更多除錯資訊
                    if js_match:
                        js_snippet = js_match.group(1)[:200] + "..." if len(js_match.group(1)) > 200 else js_match.group(1)
                        logger.debug(f"JS 資料片段: {js_snippet}")
            
            # 如果 JS 解析失敗，嘗試備用方法
            if not description:
                desc_patterns = [
                    r'<div[^>]*class="[^"]*description[^"]*"[^>]*>(.*?)</div>',
                    r'<p[^>]*>(Born in [^<]+.*?)</p>'
                ]
                
                for pattern in desc_patterns:
                    desc_match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
                    if desc_match:
                        description = re.sub(r'<[^>]+>', '', desc_match.group(1)).strip()
                        if len(description) > 20:
                            break
            
            # 從設計師頁面獲取照片
            image_url = self._get_creator_image(creator_id, slug)
            
            logger.info(f"解析結果 - 名稱: {name}, slug: {slug}, 描述長度: {len(description)}, 圖片: {bool(image_url)}")
            
            return {
                'name': name,
                'slug': slug,
                'description': description,
                'image_url': image_url
            }
            
        except Exception as e:
            logger.error(f"獲取基本資訊失敗: {e}")
            return {'name': f'Creator {creator_id}', 'slug': f'creator-{creator_id}'}
    
    def _get_creator_image(self, creator_id: int, slug: str) -> Optional[str]:
        """從設計師頁面解析獲取設計師/繪師的照片"""
        try:
            # 構建設計師頁面 URL
            page_url = f"https://boardgamegeek.com/boardgamedesigner/{creator_id}/{slug}"
            
            logger.info(f"從設計師頁面抓取照片: {page_url}")
            response = self.session.get(page_url, timeout=15)
            
            if response.status_code == 200:
                html_content = response.text
                
                # 方法1: 從 JavaScript 物件中解析圖片 URL
                import re
                # 尋找 GEEK.geekitemPreload 或類似的 JavaScript 物件
                js_pattern = r'"images":\s*\{[^}]*"imageurl":\s*"([^"]+)"'
                match = re.search(js_pattern, html_content)
                
                if match:
                    image_url = match.group(1)
                    # 處理 URL 轉義字元
                    image_url = image_url.replace('\\/', '/')
                    logger.info(f"找到設計師照片: {image_url}")
                    return image_url
                
                # 方法2: 尋找縮圖版本
                thumb_pattern = r'"images":\s*\{[^}]*"thumb":\s*"([^"]+)"'
                match = re.search(thumb_pattern, html_content)
                
                if match:
                    image_url = match.group(1)
                    image_url = image_url.replace('\\/', '/')
                    logger.info(f"找到設計師縮圖: {image_url}")
                    return image_url
                
                # 方法3: 尋找原始圖片URL模式
                original_pattern = r'"original":\s*"([^"]+)"'
                match = re.search(original_pattern, html_content)
                
                if match:
                    image_url = match.group(1)
                    image_url = image_url.replace('\\/', '/')
                    logger.info(f"找到設計師原始圖片: {image_url}")
                    return image_url
                
                logger.warning(f"設計師 {creator_id} 頁面中沒有找到照片")
                return None
            else:
                logger.error(f"設計師頁面請求失敗: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"獲取設計師 {creator_id} 照片失敗: {e}")
            return None
    
    def _get_creator_games(self, creator_id: int, slug: str, bgg_type: str, creator_name: str,
                          limit: Optional[int] = None, sort: str = 'yearpublished', page: int = 1) -> List[Dict]:
        """使用 BGG API 獲取設計師/繪師的遊戲作品"""
        try:
            # 使用官方 BGG API
            # 映射 bgg_type 到 linkdata_index
            linkdata_index_map = {
                'boardgamedesigner': 'boardgamedesigner',
                'boardgameartist': 'boardgameartist'
            }
            linkdata_index = linkdata_index_map.get(bgg_type, 'boardgamedesigner')
            
            # 構建 API URL
            api_url = "https://api.geekdo.com/api/geekitem/linkeditems"
            params = {
                'ajax': 1,
                'linkdata_index': linkdata_index,
                'nosession': 1,
                'objectid': creator_id,
                'objecttype': 'person',
                'pageid': page,
                'showcount': limit or 25,  # 預設每頁 25 個
                'sort': sort,
                'subtype': 'boardgame'
            }
            
            logger.info(f"使用 BGG API 獲取作品列表: {api_url} (ID: {creator_id}, 類型: {linkdata_index})")
            response = self.session.get(api_url, params=params, timeout=30)
            
            if response.status_code != 200:
                logger.warning(f"BGG API 請求失敗: {response.status_code}")
                return []
            
            # 解析 JSON 回應
            try:
                data = response.json()
            except json.JSONDecodeError as e:
                logger.error(f"無法解析 JSON 回應: {e}")
                return []
            
            games = []
            
            # 檢查 API 回應結構
            if not isinstance(data, dict):
                logger.warning(f"API 回應格式異常: {type(data)}")
                return []
            
            # 查找遊戲項目 - BGG API 可能有不同的結構
            items = []
            if 'items' in data:
                items = data['items']
            elif isinstance(data, list):
                items = data
            elif 'linkeditems' in data:
                items = data['linkeditems']
            
            logger.info(f"API 回應包含 {len(items)} 個項目")
            
            # 解析每個遊戲項目
            for i, item in enumerate(items):
                if limit and i >= limit:
                    break
                    
                try:
                    # 提取遊戲資訊
                    game_id = None
                    game_name = None
                    year = None
                    rating = None
                    
                    # 嘗試不同的欄位名稱
                    if 'objectid' in item:
                        game_id = int(item['objectid'])
                    elif 'id' in item:
                        game_id = int(item['id'])
                    
                    if 'name' in item:
                        game_name = item['name']
                    elif 'title' in item:
                        game_name = item['title']
                    
                    if 'yearpublished' in item:
                        try:
                            year = int(item['yearpublished'])
                        except (ValueError, TypeError):
                            year = None
                    
                    if 'average' in item:
                        try:
                            rating = float(item['average'])
                        except (ValueError, TypeError):
                            rating = None
                    elif 'rating' in item:
                        try:
                            rating = float(item['rating'])
                        except (ValueError, TypeError):
                            rating = None
                    
                    # 驗證必要資訊
                    if not game_id or not game_name:
                        logger.debug(f"跳過無效項目: {item}")
                        continue
                    
                    # 清理遊戲名稱
                    clean_name = re.sub(r'<[^>]+>', '', str(game_name)).strip()
                    
                    # 跳過無效結果
                    if (len(clean_name) < 2 or 
                        clean_name == creator_name or 
                        len(clean_name) > 100):
                        continue
                    
                    games.append({
                        'bgg_id': game_id,
                        'name': clean_name,
                        'year': year,
                        'rating': rating,
                        'rank': i + 1
                    })
                    
                except (KeyError, ValueError, TypeError) as e:
                    logger.debug(f"解析項目失敗: {e} - {item}")
                    continue
            
            logger.info(f"成功解析 {len(games)} 個遊戲")
            return games
            
        except Exception as e:
            logger.error(f"獲取作品列表失敗: {e}")
            return []
    
    def get_creator_games_paginated(self, creator_id: int, slug: str, bgg_type: str, 
                                   creator_name: str, existing_games: List[int] = None,
                                   stop_on_existing: bool = True) -> List[Dict]:
        """
        使用分頁獲取設計師/繪師的所有作品（按年份倒序）
        
        Args:
            creator_id: 設計師/繪師 ID
            slug: URL slug  
            bgg_type: BGG 類型
            creator_name: 設計師名稱
            existing_games: 已存在的遊戲 BGG ID 列表
            stop_on_existing: 是否在遇到已存在遊戲時停止（用於增量更新）
        
        Returns:
            List[Dict]: 新遊戲作品列表
        """
        all_new_games = []
        page = 1
        existing_games = set(existing_games or [])
        
        logger.info(f"開始獲取設計師 {creator_id} ({creator_name}) 的作品 (停止於已存在: {stop_on_existing})")
        
        while True:
            try:
                games = self._get_creator_games(
                    creator_id=creator_id,
                    slug=slug, 
                    bgg_type=bgg_type,
                    creator_name=creator_name,
                    limit=25,
                    sort='yearpublished', 
                    page=page
                )
                
                if not games:
                    logger.info(f"第 {page} 頁沒有更多遊戲，停止分頁")
                    break
                
                new_games_in_page = []
                for game in games:
                    if game['bgg_id'] in existing_games:
                        if stop_on_existing:
                            logger.info(f"遇到已存在遊戲 {game['name']} ({game['bgg_id']})，停止獲取")
                            all_new_games.extend(new_games_in_page)
                            return all_new_games
                        # 不停止模式，跳過已存在的遊戲
                        continue
                    else:
                        new_games_in_page.append(game)
                
                all_new_games.extend(new_games_in_page)
                
                logger.info(f"第 {page} 頁: 找到 {len(games)} 個遊戲，{len(new_games_in_page)} 個新遊戲")
                
                # 如果這頁遊戲數量少於 25，說明已經到最後一頁
                if len(games) < 25:
                    logger.info(f"第 {page} 頁遊戲數量 < 25，已到最後一頁")
                    break
                
                page += 1
                
                # 防止無限循環，最多獲取 20 頁
                if page > 20:
                    logger.warning(f"已達到最大頁數限制 (20)，停止獲取")
                    break
                    
            except Exception as e:
                logger.error(f"獲取第 {page} 頁時發生錯誤: {e}")
                break
        
        logger.info(f"總共找到 {len(all_new_games)} 個新遊戲")
        return all_new_games
    
    def get_all_creator_games(self, creator_id: int, slug: str, bgg_type: str, 
                             existing_games: List[int] = None, sort: str = 'yearpublished', 
                             limit: int = None) -> List[Dict]:
        """
        獲取設計師/繪師的所有作品 (用於追蹤時的完整同步)
        
        Args:
            creator_id: 設計師/繪師 ID
            slug: URL slug
            bgg_type: BGG 類型
            existing_games: 已存在的遊戲 ID 列表，用於增量更新
            sort: 排序方式 ('yearpublished', 'average')
            limit: 限制數量
        
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
                    'sort': sort  # 使用指定的排序方式
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
                
                # 如果設置了限制且已達到限制數量，提前結束
                if limit and len(all_games) >= limit:
                    break
                    
                page += 1
                time.sleep(1)  # 避免請求過於頻繁
                
            except Exception as e:
                logger.error(f"獲取第 {page} 頁作品失敗: {e}")
                break
        
        # 如果設置了限制，截取到指定數量
        if limit:
            all_games = all_games[:limit]
            
        return all_games
    
    def _ensure_creators_table_autoincrement(self, cursor):
        """確保 creators 表的 id 欄位有自動遞增功能"""
        try:
            # 檢查是否已經設定自動遞增
            cursor.execute("""
                SELECT column_default 
                FROM information_schema.columns 
                WHERE table_name = 'creators' AND column_name = 'id'
            """)
            result = cursor.fetchone()
            
            # 如果沒有設定 nextval，表示需要修復
            if not result or not (result[0] and 'nextval' in str(result[0])):
                logger.info("檢測到 creators 表 id 欄位缺少自動遞增，正在修復...")
                
                # 修復序列
                cursor.execute("""
                    DO $$
                    BEGIN
                        -- 創建序列（如果不存在）
                        CREATE SEQUENCE IF NOT EXISTS creators_id_seq;
                        
                        -- 設置序列的當前值為表中最大 id + 1
                        PERFORM setval('creators_id_seq', COALESCE((SELECT MAX(id) FROM creators), 0) + 1, false);
                        
                        -- 修改欄位為使用序列
                        ALTER TABLE creators ALTER COLUMN id SET DEFAULT nextval('creators_id_seq');
                        
                        -- 設置序列擁有者
                        ALTER SEQUENCE creators_id_seq OWNED BY creators.id;
                    END $$
                """)
                
                logger.info("creators 表 id 欄位自動遞增修復完成")
            else:
                logger.debug("creators 表 id 欄位自動遞增已正確設定")
                
        except Exception as e:
            logger.error(f"修復 creators 表自動遞增失敗: {e}")
            # 不拋出異常，讓主流程繼續
    
    def save_creator_to_db(self, creator_data: Dict) -> int:
        """將設計師/繪師資料儲存到資料庫"""
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # 檢查並修復 creators 表的 id 欄位自動遞增（如果需要）
                self._ensure_creators_table_autoincrement(cursor)
                
                now = datetime.now().isoformat()
                
                # 插入或更新設計師/繪師
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
                
                conn.commit()
                logger.info(f"儲存 {len(games)} 個遊戲作品")
                
        except Exception as e:
            logger.error(f"儲存遊戲作品失敗: {e}")

    def follow_creator(self, user_id: int, creator_id: int, bgg_type: str, creator_name: str) -> Dict:
        """
        用戶追蹤設計師/繪師
        
        Args:
            user_id: 用戶 ID
            creator_id: BGG 設計師 ID
            bgg_type: BGG 類型 ('boardgamedesigner' 或 'boardgameartist')
            creator_name: 設計師名稱
        
        Returns:
            Dict: 操作結果 {'success': bool, 'message': str, 'creator_db_id': int}
        """
        try:
            # 1. 獲取或創建設計師記錄
            creator_db_id = self._get_or_create_creator(creator_id, bgg_type, creator_name)
            if not creator_db_id:
                return {
                    'success': False,
                    'message': '創建設計師記錄失敗',
                    'creator_db_id': None
                }
            
            # 2. 添加追蹤記錄並獲取遊戲數量
            follow_result = self._add_user_follow(user_id, creator_db_id, creator_name)
            
            # 3. 獲取已儲存的遊戲數量並更新消息
            if follow_result['success']:
                try:
                    with get_db_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute("SELECT COUNT(*) FROM creator_games WHERE creator_id = %s", (creator_db_id,))
                        game_count = cursor.fetchone()[0]
                        follow_result['message'] = f'開始追蹤 {creator_name}，已記錄 {game_count} 個作品'
                except Exception as e:
                    logger.warning(f"無法獲取遊戲數量: {e}")
            
            return follow_result
            
        except Exception as e:
            logger.error(f"追蹤設計師失敗: {e}")
            return {
                'success': False,
                'message': f'追蹤失敗: {str(e)}',
                'creator_db_id': None
            }
    
    def _get_or_create_creator(self, creator_id: int, bgg_type: str, creator_name: str) -> int:
        """獲取或創建設計師記錄，返回資料庫 ID"""
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # 檢查是否已存在
                cursor.execute("SELECT id FROM creators WHERE bgg_id = %s", (creator_id,))
                    
                existing = cursor.fetchone()
                if existing:
                    logger.info(f"找到已存在的設計師記錄: ID {existing[0]}")
                    return existing[0]
            
            # 需要創建新記錄，先獲取詳細資訊
            logger.info(f"創建新設計師記錄: {creator_name}")
            creator_info = self.get_creator_details(creator_id, bgg_type)
            
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # 檢查並修復 creators 表的 id 欄位自動遞增（如果需要）
                self._ensure_creators_table_autoincrement(cursor)
                
                creator_type = 'designer' if bgg_type == 'boardgamedesigner' else 'artist'
                now = datetime.now().isoformat()
                
                cursor.execute("""
                    INSERT INTO creators (bgg_id, name, type, description, image_url, slug, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
                """, (creator_id, creator_info['name'], creator_type, 
                      creator_info.get('description'), creator_info.get('image_url'),
                      creator_info.get('slug'), now, now))
                creator_db_id = cursor.fetchone()[0]
                
                logger.info(f"創建設計師記錄成功: {creator_info['name']} (ID: {creator_db_id})")
                conn.commit()
                
                # 3. 獲取並儲存設計師的遊戲作品
                try:
                    slug = creator_info.get('slug')
                    if slug:
                        logger.info(f"開始獲取設計師 {creator_info['name']} 的遊戲作品...")
                        # 使用更可靠的 _get_creator_games 方法 (使用 BGG API)
                        games = self._get_creator_games(creator_id, slug, bgg_type, creator_info['name'])
                        if games:
                            self.save_creator_games(creator_db_id, games)
                            logger.info(f"已儲存 {len(games)} 個遊戲作品")
                        else:
                            logger.warning(f"未能獲取設計師 {creator_info['name']} 的遊戲作品")
                    else:
                        logger.warning(f"設計師 {creator_info['name']} 缺少 slug，無法獲取遊戲作品")
                except Exception as games_error:
                    logger.warning(f"獲取設計師 {creator_info['name']} 的遊戲作品失敗: {games_error}")
                
                return creator_db_id
                
        except Exception as e:
            logger.error(f"獲取或創建設計師失敗: {e}")
            return None
    
    def _add_user_follow(self, user_id: int, creator_db_id: int, creator_name: str) -> Dict:
        """添加用戶追蹤記錄"""
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # 檢查是否已追蹤
                cursor.execute("SELECT 1 FROM user_follows WHERE user_id = %s AND creator_id = %s", 
                             (user_id, creator_db_id))
                
                if cursor.fetchone():
                    return {
                        'success': False,
                        'message': f'您已經在追蹤 {creator_name} 了',
                        'creator_db_id': creator_db_id
                    }
                
                # 添加追蹤記錄
                follow_time = datetime.now().isoformat()
                cursor.execute("""
                    INSERT INTO user_follows (user_id, creator_id, followed_at)
                    VALUES (%s, %s, %s)
                """, (user_id, creator_db_id, follow_time))
                
                logger.info(f"用戶 {user_id} 開始追蹤設計師 {creator_name} (DB ID: {creator_db_id})")
                conn.commit()
                
                return {
                    'success': True,
                    'message': f'成功追蹤 {creator_name}！我們會在有新作品時通知您。',
                    'creator_db_id': creator_db_id
                }
                
        except Exception as e:
            logger.error(f"添加追蹤記錄失敗: {e}")
            return {
                'success': False,
                'message': f'追蹤失敗: {str(e)}',
                'creator_db_id': None
            }

    def _sync_creator_games_to_db(self, creator_db_id: int, creator_bgg_id: int, 
                                  bgg_type: str, creator_name: str) -> int:
        """
        同步設計師遊戲到資料庫（增量更新）
        
        Returns:
            int: 新增的遊戲數量
        """
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # 獲取已存在的遊戲 BGG ID
                cursor.execute("SELECT bgg_game_id FROM creator_games WHERE creator_id = %s", 
                             (creator_db_id,))
                
                existing_game_ids = [row[0] for row in cursor.fetchall()]
            
                # 獲取新遊戲（按年份倒序，遇到已存在的就停止）
                new_games = self.get_creator_games_paginated(
                    creator_id=creator_bgg_id,
                    slug="",  # 不需要 slug
                    bgg_type=bgg_type,
                    creator_name=creator_name,
                    existing_games=existing_game_ids,
                    stop_on_existing=True  # 遇到已存在的遊戲就停止
                )
                
                if not new_games:
                    logger.info(f"設計師 {creator_name} 沒有新遊戲")
                    return 0
                
                # 儲存新遊戲到資料庫
                now = datetime.now().isoformat()
                
                for game in new_games:
                    cursor.execute("""
                        INSERT INTO creator_games 
                        (creator_id, bgg_game_id, game_name, year_published, rating, rank_position, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (creator_id, bgg_game_id) DO NOTHING
                    """, (creator_db_id, game['bgg_id'], game['name'],
                          game.get('year'), game.get('rating'), game.get('rank'), now))
                
                logger.info(f"設計師 {creator_name} 新增 {len(new_games)} 個遊戲作品")
                return len(new_games)
            
        except Exception as e:
            logger.error(f"同步設計師遊戲失敗: {e}")
            return 0

    def update_all_followed_creators(self) -> Dict:
        """
        更新所有被追蹤設計師的作品（用於定期執行）
        
        Returns:
            Dict: 更新結果統計
        """
        try:
            # 獲取所有被追蹤的設計師
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT DISTINCT c.id, c.bgg_id, c.name, c.type
                    FROM creators c 
                    JOIN user_follows uf ON c.id = uf.creator_id
                """)
                followed_creators = cursor.fetchall()
            
            stats = {
                'total_creators': len(followed_creators),
                'updated_creators': 0,
                'new_games_found': 0,
                'errors': 0,
                'details': []
            }
            
            logger.info(f"開始更新 {len(followed_creators)} 個被追蹤的設計師")
            
            for creator_db_id, creator_bgg_id, creator_name, creator_type in followed_creators:
                try:
                    # 轉換類型
                    bgg_type = 'boardgamedesigner' if creator_type == 'designer' else 'boardgameartist'
                    
                    # 同步新遊戲
                    new_games_count = self._sync_creator_games_to_db(
                        creator_db_id, creator_bgg_id, bgg_type, creator_name
                    )
                    
                    stats['updated_creators'] += 1
                    stats['new_games_found'] += new_games_count
                    
                    creator_stats = {
                        'name': creator_name,
                        'new_games': new_games_count,
                        'success': True
                    }
                    stats['details'].append(creator_stats)
                    
                    if new_games_count > 0:
                        logger.info(f"設計師 {creator_name} 新增了 {new_games_count} 個遊戲")
                    
                    # 避免 API 限流
                    time.sleep(1)
                    
                except Exception as e:
                    logger.error(f"更新設計師 {creator_name} 失敗: {e}")
                    stats['errors'] += 1
                    stats['details'].append({
                        'name': creator_name,
                        'new_games': 0,
                        'success': False,
                        'error': str(e)
                    })
            
            logger.info(f"更新完成: {stats['updated_creators']} 個設計師, {stats['new_games_found']} 個新遊戲")
            return stats
            
        except Exception as e:
            logger.error(f"批量更新失敗: {e}")
            return {
                'total_creators': 0,
                'updated_creators': 0,
                'new_games_found': 0,
                'errors': 1,
                'details': [],
                'error': str(e)
            }

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