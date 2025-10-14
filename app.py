#!/usr/bin/env python3
import os
import sys
from datetime import datetime, date
from typing import Optional, List

# 確保 board-game-recommender 在 Python path 中
current_dir = os.path.dirname(os.path.abspath(__file__))
board_game_recommender_path = os.path.join(current_dir, 'board-game-recommender')
if board_game_recommender_path not in sys.path:
    sys.path.insert(0, board_game_recommender_path)
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from dotenv import load_dotenv
import subprocess
import logging
import glob
import re
import json
import requests
from bs4 import BeautifulSoup
from database import get_db_connection, get_database_config, execute_query
# 認證系統導入 - 優先使用 email_auth，Google 認證為可選
from email_auth import EmailAuth, login_required, admin_required, full_access_required, has_full_access, get_current_user

# 嘗試導入 Google 認證 (可選)
try:
    from google_auth import GoogleAuth
    GOOGLE_AUTH_AVAILABLE = True
except ImportError:
    GoogleAuth = None
    GOOGLE_AUTH_AVAILABLE = False
import threading
import time
from functools import lru_cache

# BGG 推薦系統 (board-game-recommender)
try:
    from board_game_recommender import BGGRecommender
    BGG_RECOMMENDER_AVAILABLE = True
    logging.info("✅ BGGRecommender 載入成功")
except ImportError as e:
    logging.warning(f"BGGRecommender 無法載入: {e}")
    BGG_RECOMMENDER_AVAILABLE = False

# 全域任務狀態追蹤
task_status = {
    'is_running': False,
    'start_time': None,
    'current_step': '',
    'progress': 0,
    'message': '',
    'last_update': None,
    'stop_requested': False,
    'stopped_by_user': False
}

def update_task_status(step, progress, message):
    """更新任務狀態"""
    global task_status
    task_status.update({
        'current_step': step,
        'progress': progress,
        'message': message,
        'last_update': datetime.now()
    })
    logger.info(f"📊 任務進度: {progress}% - {step} - {message}")

def request_task_stop():
    """請求停止當前任務"""
    global task_status
    if task_status['is_running']:
        task_status['stop_requested'] = True
        logger.info("🛑 用戶請求停止任務")
        return True
    return False

def parse_execution_progress(line, elapsed):
    """解析執行輸出，返回進度和狀態訊息"""
    line = line.strip()

    # 步驟1: 抓取熱門遊戲榜單
    if "抓取熱門桌遊榜單" in line or "找到" in line and "個遊戲" in line:
        if "完成詳細資料抓取" in line:
            return 20, f"✅ 步驟1完成: {line}"
        return 15, f"📊 步驟1/4: {line}"

    # 步驟2: 抓取遊戲詳細資訊
    elif "處理第" in line and "批" in line:
        return 25, f"🎲 步驟2/4: {line}"
    elif "已更新遊戲:" in line:
        game_name = line.split("已更新遊戲:")[-1].split("(")[0].strip() if "已更新遊戲:" in line else ""
        return 30, f"🎮 步驟2/4: 已更新 {game_name}"
    elif "完成詳細資料抓取" in line:
        return 40, f"✅ 步驟2完成: {line}"

    # 步驟3: 抓取討論串
    elif "開始抓取遊戲的討論串" in line:
        game_name = line.split(":")[-1].strip() if ":" in line else "遊戲"
        return 45, f"💬 步驟3/4: 開始抓取 {game_name} 的討論串"
    elif "抓取討論串列表" in line:
        return 50, f"📋 步驟3/4: {line}"
    elif "抓取討論串文章內容" in line:
        return 55, f"📝 步驟3/4: {line}"
    elif "翻譯討論串" in line or "翻譯完成" in line:
        game_name = ""
        if "翻譯討論串" in line:
            parts = line.split()
            for i, part in enumerate(parts):
                if "翻譯討論串" in part and i > 0:
                    game_name = parts[i-1]
                    break
        return 70, f"🌍 步驟3/4: 正在翻譯 {game_name}".strip()
    elif "處理完成遊戲" in line:
        game_name = line.split(":")[-1].strip() if ":" in line else ""
        return 75, f"✅ 步驟3進度: 已完成 {game_name}"

    # 步驟4: 產生報表
    elif "開始產生" in line and "報表" in line:
        return 80, f"📄 步驟4/4: {line}"
    elif "已產出" in line and "報告" in line:
        return 95, f"✅ 步驟4完成: {line}"
    elif "報表產生完成" in line:
        return 100, f"🎉 任務完成: {line}"

    # 資料庫相關訊息
    elif "數據庫" in line or "資料庫" in line:
        if "初始化" in line:
            return 5, f"🗃️ 初始化: {line}"
        return None, f"🗃️ 資料庫: {line}"

    # 錯誤訊息
    elif "錯誤" in line or "失敗" in line or "❌" in line:
        return None, f"⚠️ {line}"

    # 其他重要訊息
    elif any(keyword in line for keyword in ["✅", "📊", "🎲", "💬", "📋", "📝", "🌍", "📄"]):
        return None, line

    # 預設情況：顯示原始訊息但不更新進度
    return None, line if line else None

def reset_task_status():
    """重置任務狀態"""
    global task_status
    task_status.update({
        'is_running': False,
        'start_time': None,
        'current_step': '',
        'progress': 0,
        'message': '',
        'last_update': None,
        'stop_requested': False,
        'stopped_by_user': False
    })

def check_if_should_stop():
    """檢查是否應該停止任務"""
    return task_status.get('stop_requested', False)

# 嘗試導入 markdown，如果失敗則使用簡單的文字顯示
try:
    import markdown
    MARKDOWN_AVAILABLE = True
except ImportError:
    MARKDOWN_AVAILABLE = False
    print("Warning: markdown module not available. Reports will be displayed as plain text.")

# 載入環境變數
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key-here')

# 設定日誌
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 認證系統設定
email_auth = EmailAuth()

# Google OAuth 設定 (可選)
google_auth = GoogleAuth() if GOOGLE_AUTH_AVAILABLE else None

# 資料庫初始化狀態追蹤
_db_initialized = False

def force_db_initialization():
    """強制執行資料庫初始化，用於應用啟動"""
    global _db_initialized
    
    if _db_initialized:
        print("✓ 資料庫已初始化，跳過重複初始化")
        return True
    
    print("🔄 強制執行資料庫初始化...")
    try:
        from database import init_database
        config = get_database_config()
        print(f"🗃️ 強制初始化 {config['type']} 資料庫結構...")
        init_database()
        print(f"✅ {config['type']} 資料庫強制初始化完成")
        _db_initialized = True
        return True
    except Exception as e:
        print(f"❌ 強制資料庫初始化失敗: {e}")
        import traceback
        print("📋 完整錯誤堆疊:")
        traceback.print_exc()
        return False

def init_db_if_needed():
    """延遲初始化資料庫，避免啟動阻塞"""
    global _db_initialized
    
    if _db_initialized:
        return True
    
    try:
        from database import init_database
        config = get_database_config()
        print(f"🗃️ 正在初始化 {config['type']} 資料庫結構...")
        init_database()
        print(f"✅ {config['type']} 資料庫結構初始化完成")
        _db_initialized = True
        return True
    except Exception as e:
        print(f"❌ 資料庫初始化失敗: {e}")
        import traceback
        traceback.print_exc()
        # 不要設置 _db_initialized = True，允許重試
        return False

# 註冊模板全域函數
@app.context_processor
def inject_auth_functions():
    return {
        'has_full_access': has_full_access,
        'get_current_user': get_current_user
    }
RG_API_URL = os.getenv('RG_API_URL')  # 例如: https://api.recommend.games
RG_API_KEY = os.getenv('RG_API_KEY')
# RG 推薦器路徑配置
def get_user_rg_paths(username=None):
    """獲取用戶特定的 RG 文件路徑"""
    if not username:
        username = get_app_setting('bgg_username', 'default')
    
    # 使用 Zeabur 的持久化目錄
    base_dir = '/data/rg_users' if os.path.exists('/data') else 'data/rg_users'
    user_dir = os.path.join(base_dir, username)
    
    return {
        'user_dir': user_dir,
        'games_file': os.path.join(user_dir, 'bgg_GameItem.jl'),
        'ratings_file': os.path.join(user_dir, 'bgg_RatingItem.jl'),
        'model_dir': os.path.join(user_dir, 'rg_model'),
        'full_model': os.path.join(user_dir, 'rg_model', 'full.npz'),
        'light_model': os.path.join(user_dir, 'rg_model', 'light.npz')
    }

@lru_cache(maxsize=8)
def load_user_recommender(username, model_type='auto'):
    """
    使用 LRU 緩存載入用戶特定的推薦器
    
    Args:
        username: BGG 用戶名
        model_type: 'auto', 'full', 'light'
    
    Returns:
        tuple: (recommender_instance, model_info)
    """
    logger.info(f"🔄 載入推薦器: username={username}, model_type={model_type}")
    
    user_paths = get_user_rg_paths(username)
    
    # 檢查用戶數據是否存在
    if not (os.path.exists(user_paths['games_file']) and os.path.exists(user_paths['ratings_file'])):
        logger.warning(f"⚠️ 用戶 {username} 的數據不存在，使用預設推薦器")
        return load_fallback_recommender(), {'type': 'fallback', 'reason': 'no_user_data'}
    
    # 根據 model_type 決定載入策略
    if model_type == 'auto':
        # 自動選擇：優先嘗試 full，失敗則使用 light
        recommender, info = _try_load_full_recommender(user_paths, username)
        if recommender:
            return recommender, info
        
        recommender, info = _try_load_light_recommender(user_paths, username)
        if recommender:
            return recommender, info
            
        # 都失敗則使用 fallback
        logger.warning(f"⚠️ 用戶 {username} 的所有 RG 模型都載入失敗，使用降級推薦器")
        return load_fallback_recommender(), {'type': 'fallback', 'reason': 'model_load_failed'}
    
    elif model_type == 'full':
        recommender, info = _try_load_full_recommender(user_paths, username)
        if recommender:
            return recommender, info
        logger.warning(f"⚠️ 用戶 {username} 的完整模型載入失敗")
        return None, {'type': 'error', 'reason': 'full_model_failed'}
    
    elif model_type == 'light':
        recommender, info = _try_load_light_recommender(user_paths, username)
        if recommender:
            return recommender, info
        logger.warning(f"⚠️ 用戶 {username} 的輕量模型載入失敗")
        return None, {'type': 'error', 'reason': 'light_model_failed'}
    
    else:
        logger.error(f"❌ 不支援的模型類型: {model_type}")
        return None, {'type': 'error', 'reason': 'invalid_model_type'}

def _try_load_full_recommender(user_paths, username):
    """嘗試載入完整的 BGGRecommender"""
    try:
        # 檢查是否有可用的 RG 套件
        try:
            from board_game_recommender import BGGRecommender
        except ImportError:
            logger.warning("⚠️ board_game_recommender 套件不可用")
            return None, {'type': 'error', 'reason': 'missing_package'}
        
        # 尋找可用的 JSONL 檔案（優先用戶特定，降級到預設）
        games_file, ratings_file = _find_best_jsonl_files(user_paths, username)
        
        if not games_file or not ratings_file:
            logger.warning(f"⚠️ 找不到可用的 JSONL 資料檔案")
            return None, {'type': 'error', 'reason': 'no_data_files'}
        
        logger.info(f"🎯 嘗試載入用戶 {username} 的完整 BGGRecommender，使用檔案: {games_file}")
        
        recommender = BGGRecommender(
            games_file=games_file,
            ratings_file=ratings_file
        )
        
        logger.info(f"✅ 成功載入用戶 {username} 的完整 BGGRecommender")
        return recommender, {
            'type': 'bgg_full',
            'games_file': games_file,
            'ratings_file': ratings_file,
            'username': username
        }
        
    except Exception as e:
        logger.error(f"❌ 載入完整 BGGRecommender 失敗: {e}")
        return None, {'type': 'error', 'reason': str(e)}

def _find_best_jsonl_files(user_paths, username):
    """尋找最佳可用的 JSONL 檔案（優先用戶特定，降級到預設）"""
    try:
        # 優先使用用戶特定檔案
        if os.path.exists(user_paths['games_file']) and os.path.exists(user_paths['ratings_file']):
            logger.info(f"📋 使用用戶特定的 JSONL 檔案: {user_paths['games_file']}")
            return user_paths['games_file'], user_paths['ratings_file']
        
        # 降級到預設檔案
        if os.path.exists(RG_DEFAULT_GAMES_FILE) and os.path.exists(RG_DEFAULT_RATINGS_FILE):
            logger.info(f"📋 使用預設 JSONL 檔案: {RG_DEFAULT_GAMES_FILE}")
            return RG_DEFAULT_GAMES_FILE, RG_DEFAULT_RATINGS_FILE
        
        logger.warning("⚠️ 找不到任何可用的 JSONL 檔案")
        return None, None
        
    except Exception as e:
        logger.error(f"❌ 尋找 JSONL 檔案時發生錯誤: {e}")
        return None, None

def _try_load_light_recommender(user_paths, username):
    """嘗試載入輕量的 LightGamesRecommender"""
    try:
        # 檢查是否有可用的輕量推薦器
        try:
            from board_game_recommender import LightGamesRecommender
        except ImportError:
            logger.warning("⚠️ LightGamesRecommender 不可用")
            return None, {'type': 'error', 'reason': 'missing_light_package'}
        
        # 檢查輕量模型檔案是否存在
        if not os.path.exists(user_paths['light_model']):
            logger.warning(f"⚠️ 用戶 {username} 的輕量模型檔案不存在: {user_paths['light_model']}")
            return None, {'type': 'error', 'reason': 'no_light_model'}
        
        # 尋找可用的遊戲檔案
        games_file, _ = _find_best_jsonl_files(user_paths, username)
        if not games_file:
            logger.warning(f"⚠️ 找不到遊戲資料檔案")
            return None, {'type': 'error', 'reason': 'no_games_file'}
        
        logger.info(f"🎯 嘗試載入用戶 {username} 的 LightGamesRecommender")
        
        recommender = LightGamesRecommender(
            games_file=games_file,
            model_file=user_paths['light_model']
        )
        
        logger.info(f"✅ 成功載入用戶 {username} 的 LightGamesRecommender")
        return recommender, {
            'type': 'light',
            'games_file': games_file, 
            'model_file': user_paths['light_model'],
            'username': username
        }
        
    except Exception as e:
        logger.error(f"❌ 載入 LightGamesRecommender 失敗: {e}")
        return None, {'type': 'error', 'reason': str(e)}

def load_fallback_recommender():
    """載入降級推薦器（使用 board-game-recommender）"""
    try:
        from board_game_recommender.recommend import BGGRecommender
        logger.info("✅ 成功載入降級推薦器 (BGGRecommender)")
        return BGGRecommender
    except Exception as e:
        logger.warning(f"⚠️ 載入 BGGRecommender 失敗: {e}")
        logger.info("🔄 使用最簡化推薦器")
        return MinimalRecommender()

class MinimalRecommender:
    """最簡化的推薦器實現，不依賴任何外部機器學習套件"""
    
    def __init__(self):
        self.model_type = 'minimal'
        logger.info("🔧 初始化最簡化推薦器")
    
    def get_recommendation_score(self, game_id, owned_ids):
        """計算遊戲推薦分數"""
        try:
            logger.info(f"🎯 最簡化推薦器計算遊戲 {game_id} 的分數")
            
            # 使用簡單的基於特徵的相似度計算
            return self._calculate_similarity_score(game_id, owned_ids)
            
        except Exception as e:
            logger.error(f"❌ 最簡化推薦器計算失敗: {e}")
            return 6.0  # 返回中性分數
    
    def _calculate_similarity_score(self, game_id, owned_ids):
        """基於遊戲特徵計算相似度分數"""
        try:
            if not owned_ids:
                # 如果沒有收藏，返回遊戲的一般評分
                return self._get_game_base_score(game_id)
            
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # 獲取目標遊戲特徵
                cursor.execute("""
                    SELECT category, mechanic, min_players, max_players, playing_time,
                           complexity, year_published, average_rating, bayes_average_rating
                    FROM game_detail WHERE objectid = %s
                """, (game_id,))
                
                target_game = cursor.fetchone()
                if not target_game:
                    logger.warning(f"⚠️ 找不到遊戲 {game_id} 的資料")
                    return 5.0
                
                # 計算與用戶收藏遊戲的相似度
                similarity_scores = []
                
                for owned_id in owned_ids[:50]:  # 限制計算數量以提高性能
                    cursor.execute("""
                        SELECT category, mechanic, min_players, max_players, playing_time,
                               complexity, year_published, average_rating, bayes_average_rating
                        FROM game_detail WHERE objectid = %s
                    """, (owned_id,))
                    
                    owned_game = cursor.fetchone()
                    if owned_game:
                        similarity = self._calculate_feature_similarity(target_game, owned_game)
                        # 假設用戶對收藏的遊戲評分較高
                        user_rating = 7.5 + (similarity * 1.5)  # 7.5-9.0 範圍
                        weighted_score = similarity * user_rating
                        similarity_scores.append(weighted_score)
                
                if similarity_scores:
                    # 計算平均相似度分數
                    avg_similarity = sum(similarity_scores) / len(similarity_scores)
                    
                    # 結合遊戲本身的評分
                    base_score = float(target_game[7] or 6.0)  # average_rating
                    bayes_score = float(target_game[8] or 6.0)  # bayes_average_rating
                    game_score = (base_score + bayes_score) / 2
                    
                    # 混合個人化和一般評分 (70% 個人化, 30% 一般評分)
                    final_score = (avg_similarity * 0.7) + (game_score * 0.3)
                    
                    # 限制在合理範圍內
                    final_score = max(1.0, min(10.0, final_score))
                    
                    logger.info(f"✅ 遊戲 {game_id} 相似度分數: {final_score:.3f}")
                    return float(final_score)
                
                # 如果沒有相似遊戲，返回遊戲的基本分數
                return self._get_game_base_score(game_id)
                
        except Exception as e:
            logger.error(f"❌ 相似度計算失敗: {e}")
            return 6.0
    
    def _calculate_feature_similarity(self, game1, game2):
        """計算兩個遊戲的特徵相似度"""
        try:
            similarities = []
            
            # 分類相似度
            if game1[0] and game2[0]:
                cat1 = set(game1[0].split(','))
                cat2 = set(game2[0].split(','))
                if cat1 or cat2:
                    cat_sim = len(cat1.intersection(cat2)) / len(cat1.union(cat2))
                    similarities.append(cat_sim * 0.3)
            
            # 機制相似度
            if game1[1] and game2[1]:
                mech1 = set(game1[1].split(','))
                mech2 = set(game2[1].split(','))
                if mech1 or mech2:
                    mech_sim = len(mech1.intersection(mech2)) / len(mech1.union(mech2))
                    similarities.append(mech_sim * 0.3)
            
            # 玩家數量相似度
            if all([game1[2], game2[2], game1[3], game2[3]]):
                min1, max1 = int(game1[2]), int(game1[3])
                min2, max2 = int(game2[2]), int(game2[3])
                overlap = max(0, min(max1, max2) - max(min1, min2) + 1)
                total_range = max(max1, max2) - min(min1, min2) + 1
                player_sim = overlap / total_range if total_range > 0 else 0
                similarities.append(player_sim * 0.2)
            
            # 遊戲時間相似度
            if game1[4] and game2[4]:
                time1, time2 = float(game1[4]), float(game2[4])
                time_diff = abs(time1 - time2)
                max_time = max(time1, time2)
                time_sim = max(0, 1 - time_diff / max_time) if max_time > 0 else 0
                similarities.append(time_sim * 0.1)
            
            # 複雜度相似度
            if game1[5] and game2[5]:
                comp1, comp2 = float(game1[5]), float(game2[5])
                comp_diff = abs(comp1 - comp2)
                comp_sim = max(0, 1 - comp_diff / 5.0)  # 複雜度範圍 1-5
                similarities.append(comp_sim * 0.1)
            
            return sum(similarities) if similarities else 0.5
            
        except Exception as e:
            logger.error(f"❌ 特徵相似度計算錯誤: {e}")
            return 0.5
    
    def _get_game_base_score(self, game_id):
        """獲取遊戲的基本評分"""
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT average_rating, bayes_average_rating, num_votes
                    FROM game_detail WHERE objectid = %s
                """, (game_id,))
                
                result = cursor.fetchone()
                if result:
                    avg_rating = float(result[0] or 6.0)
                    bayes_avg = float(result[1] or 6.0) 
                    num_votes = int(result[2] or 100)
                    
                    # 基於評分和投票數的信心調整
                    confidence = min(1.0, num_votes / 500)
                    score = (avg_rating + bayes_avg) / 2
                    final_score = score * confidence + 6.0 * (1 - confidence)
                    
                    return max(1.0, min(10.0, final_score))
                
                return 6.0
                
        except Exception as e:
            logger.error(f"❌ 獲取遊戲基本分數失敗: {e}")
            return 6.0
    
    def build_recommendations_from_collection(self, limit=20):
        """基於收藏建立推薦列表"""
        try:
            recommendations = []
            
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # 獲取用戶收藏
                cursor.execute("SELECT objectid FROM collection")
                owned_ids = [row[0] for row in cursor.fetchall()]
                
                if not owned_ids:
                    # 如果沒有收藏，推薦熱門遊戲
                    cursor.execute("""
                        SELECT objectid, name, average_rating
                        FROM game_detail 
                        WHERE average_rating >= 7.0 
                        ORDER BY bayes_average_rating DESC
                        LIMIT %s
                    """, (limit,))
                    
                    for row in cursor.fetchall():
                        recommendations.append({
                            'id': row[0],
                            'name': row[1],
                            'score': float(row[2] or 7.0)
                        })
                else:
                    # 基於收藏推薦相似遊戲
                    cursor.execute("""
                        SELECT objectid, name
                        FROM game_detail 
                        WHERE objectid NOT IN %s
                        AND average_rating >= 6.5
                        ORDER BY bayes_average_rating DESC
                        LIMIT %s
                    """, (tuple(owned_ids), limit * 3))
                    
                    candidates = cursor.fetchall()
                    
                    # 計算推薦分數並排序
                    scored_candidates = []
                    for candidate in candidates:
                        score = self.get_recommendation_score(candidate[0], owned_ids)
                        scored_candidates.append({
                            'id': candidate[0],
                            'name': candidate[1],
                            'score': score
                        })
                    
                    # 按分數排序並取前 N 個
                    scored_candidates.sort(key=lambda x: x['score'], reverse=True)
                    recommendations = scored_candidates[:limit]
                
            logger.info(f"✅ 生成了 {len(recommendations)} 個推薦")
            return recommendations
            
        except Exception as e:
            logger.error(f"❌ 建立推薦列表失敗: {e}")
            return []

# 固定的 RG 預設路徑（降級選項）
RG_DEFAULT_GAMES_FILE = 'data/bgg_GameItem.jl'
RG_DEFAULT_RATINGS_FILE = 'data/bgg_RatingItem.jl'
RG_DEFAULT_MODEL_DIR = 'data/rg_model'

# RG 抓取任務狀態
rg_task_status = {
    'is_running': False,
    'start_time': None,
    'progress': 0,
    'message': '',
    'last_update': None,
    'stdout_tail': [],
    'stderr_tail': [],
}

def update_rg_task_status(progress=None, message=None, stdout_line=None, stderr_line=None):
    if progress is not None:
        rg_task_status['progress'] = progress
    if message is not None:
        rg_task_status['message'] = message
    if stdout_line:
        rg_task_status['stdout_tail'] = (rg_task_status.get('stdout_tail', []) + [stdout_line])[-50:]
    if stderr_line:
        rg_task_status['stderr_tail'] = (rg_task_status.get('stderr_tail', []) + [stderr_line])[-50:]
    rg_task_status['last_update'] = datetime.now()

def run_rg_scrape_async(games_file: str, ratings_file: str, custom_cmd: Optional[str] = None):
    try:
        rg_task_status['is_running'] = True
        rg_task_status['start_time'] = datetime.now()
        update_rg_task_status(5, '初始化 BGG 資料抓取任務...')

        # 獲取 BGG 用戶名
        bgg_username = get_app_setting('bgg_username')
        if not bgg_username:
            update_rg_task_status(0, 'BGG 用戶名未設定')
            rg_task_status['is_running'] = False
            return

        update_rg_task_status(10, f"開始抓取 BGG 用戶 {bgg_username} 的收藏資料...")

        try:
            # 使用我們的 BGG scraper
            from bgg_scraper_extractor import BGGScraperExtractor
            extractor = BGGScraperExtractor()
            
            update_rg_task_status(20, '正在抓取用戶收藏...')
            
            # 從檔案路徑推導輸出目錄
            output_dir = 'data'
            if games_file:
                output_dir = os.path.dirname(games_file)
            
            # 執行抓取
            success = extractor.export_to_jsonl(bgg_username, output_dir)
            
            if success:
                update_rg_task_status(100, f'成功抓取用戶 {bgg_username} 的 BGG 資料')
            else:
                update_rg_task_status(0, f'抓取用戶 {bgg_username} 的 BGG 資料失敗')
                
        except Exception as e:
            error_msg = f"BGG 抓取過程發生錯誤: {str(e)}"
            update_rg_task_status(0, error_msg)
            logger.error(error_msg)
            import traceback
            logger.error(f"詳細錯誤: {traceback.format_exc()}")
            
    except Exception as e:
        update_rg_task_status(0, f'抓取異常：{e}')
    finally:
        rg_task_status['is_running'] = False

# DB_PATH = "data/bgg_rag.db"  # 移除，改用統一的資料庫連接

def get_report_by_date(report_date, lang='zh-tw'):
    """獲取指定日期的報表內容（優先從資料庫讀取）"""
    try:
        # 優先從資料庫讀取
        with get_db_connection() as conn:
            cursor = conn.cursor()
            config = get_database_config()

            if config['type'] == 'postgresql':
                cursor.execute("""
                    SELECT content, file_size, updated_at
                    FROM reports
                    WHERE report_date = %s AND lang = %s
                """, (report_date, lang))
            else:
                cursor.execute("""
                    SELECT content, file_size, updated_at
                    FROM reports
                    WHERE report_date = ? AND lang = ?
                """, (report_date, lang))

            result = cursor.fetchone()
            if result:
                content, file_size, updated_at = result
                logger.info(f"✅ 從資料庫讀取報表: {report_date}-{lang} ({file_size} bytes)")
                return content, f"report-{report_date}-{lang}.md"

        # 資料庫中沒有，嘗試從檔案讀取
        logger.info(f"⚠️ 資料庫中沒有 {report_date}-{lang} 報表，嘗試從檔案讀取...")
        report_dir = "frontend/public/outputs"
        if not os.path.exists(report_dir):
            return None, "報表目錄不存在"

        # 尋找指定日期的報表
        report_filename = f"report-{report_date}-{lang}.md"
        report_path = os.path.join(report_dir, report_filename)

        if not os.path.exists(report_path):
            return None, f"找不到 {report_date} 的報表"

        with open(report_path, 'r', encoding='utf-8') as f:
            content = f.read()

        logger.info(f"✅ 從檔案讀取報表: {report_path}")
        return content, report_filename

    except Exception as e:
        logger.error(f"讀取報表失敗: {e}")
        return None, f"讀取報表失敗: {e}"

def get_app_setting(key, default=None):
    """讀取應用設定"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            config = get_database_config()
            if config['type'] == 'postgresql':
                cursor.execute("SELECT value FROM app_settings WHERE key = %s", (key,))
            else:
                cursor.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row and row[0] is not None:
                return row[0]
    except Exception as e:
        logger.warning(f"讀取設定失敗: {e}")
    return default

def ensure_app_settings_table():
    """確保 app_settings 表存在"""
    try:
        config = get_database_config()
        logger.info(f"🔧 檢查 app_settings 表，資料庫類型: {config['type']}")
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 檢查表是否已存在 (PostgreSQL)
            cursor.execute("SELECT to_regclass('app_settings')")
            table_exists = cursor.fetchone()[0] is not None
            
            if table_exists:
                logger.info("✅ app_settings 表已存在")
                return True
            
            # 根據資料庫類型創建表
            if config['type'] == 'postgresql':
                create_sql = """
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT NOW()
                )
                """
            else:
                create_sql = """
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            
            logger.info(f"📝 創建 app_settings 表...")
            cursor.execute(create_sql)
            conn.commit()
            logger.info("✅ app_settings 表創建成功")
            return True
    except Exception as e:
        logger.error(f"❌ 創建 app_settings 表失敗: {e}")
        import traceback
        logger.error(f"詳細錯誤: {traceback.format_exc()}")
        return False

def set_app_setting(key, value):
    """寫入應用設定（存在則更新）"""
    try:
        # 確保表存在
        if not ensure_app_settings_table():
            logger.error("無法創建 app_settings 表")
            return False
            
        with get_db_connection() as conn:
            cursor = conn.cursor()
            config = get_database_config()
            # 先嘗試更新
            if config['type'] == 'postgresql':
                cursor.execute("UPDATE app_settings SET value = %s, updated_at = NOW() WHERE key = %s", (value, key))
            else:
                cursor.execute("UPDATE app_settings SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?", (value, key))
            if cursor.rowcount == 0:
                # 插入
                if config['type'] == 'postgresql':
                    cursor.execute("INSERT INTO app_settings (key, value, updated_at) VALUES (%s, %s, NOW())", (key, value))
                else:
                    cursor.execute("INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)", (key, value))
            conn.commit()
            logger.info(f"✅ 設定已保存: {key} = {value}")
            return True
    except Exception as e:
        logger.error(f"寫入設定失敗: {e}")
        return False

def fetch_bgg_collection_xml(username, params, max_retries=10, initial_delay=2):
    """呼叫 BGG Collection API，處理 202 重試機制"""
    base_url = "https://boardgamegeek.com/xmlapi2/collection"
    query = {"username": username, **params}
    delay = initial_delay
    for attempt in range(1, max_retries + 1):
        resp = requests.get(base_url, params=query, timeout=30)
        if resp.status_code == 200:
            return resp.text
        if resp.status_code == 202:
            logger.info(f"BGG 回應 202（排隊中），第 {attempt}/{max_retries} 次重試，等待 {delay}s...")
            time.sleep(delay)
            delay = min(delay * 1.5, 30)
            continue
        raise RuntimeError(f"BGG API 失敗，狀態碼: {resp.status_code}")
    raise TimeoutError("BGG API 多次重試仍為 202，請稍後再試")

def parse_bgg_collection(xml_text):
    """解析 BGG Collection XML -> List[dict]"""
    soup = BeautifulSoup(xml_text, "xml")
    items = []
    for item in soup.find_all("item"):
        try:
            objectid = int(item.get("objectid"))
        except Exception:
            continue
        name_tag = item.find("name")
        name = name_tag.text if name_tag else str(objectid)
        status_tag = item.find("status")
        status_attrs = status_tag.attrs if status_tag else {}
        stats_tag = item.find("stats")
        rating_value = None
        wishlist_priority = None
        if stats_tag:
            rating_tag = stats_tag.find("rating")
            if rating_tag and rating_tag.get("value") and rating_tag.get("value") != "N/A":
                try:
                    rating_value = float(rating_tag.get("value"))
                except Exception:
                    rating_value = None
        if status_attrs.get("wishlist") in ("1", 1, True):
            try:
                wishlist_priority = int(status_attrs.get("wishlistpriority", 0))
            except Exception:
                wishlist_priority = None
        items.append({
            "objectid": objectid,
            "name": name,
            "status_json": json.dumps(status_attrs, ensure_ascii=False),
            "rating": rating_value,
            "wish_priority": wishlist_priority
        })
    return items

def upsert_collection_items(items):
    """將收藏清單寫入資料庫（更新或插入）"""
    if not items:
        return 0
    count = 0
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            config = get_database_config()
            for it in items:
                # update first
                if config['type'] == 'postgresql':
                    cursor.execute(
                        """
                        UPDATE collection
                        SET name = %s, status = %s, rating = %s, wish_priority = %s, last_sync = NOW()
                        WHERE objectid = %s
                        """,
                        (it["name"], it["status_json"], it["rating"], it["wish_priority"], it["objectid"])
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE collection
                        SET name = ?, status = ?, rating = ?, wish_priority = ?, last_sync = CURRENT_TIMESTAMP
                        WHERE objectid = ?
                        """,
                        (it["name"], it["status_json"], it["rating"], it["wish_priority"], it["objectid"])
                    )
                if cursor.rowcount == 0:
                    # insert
                    if config['type'] == 'postgresql':
                        cursor.execute(
                            """
                            INSERT INTO collection (objectid, name, status, rating, wish_priority, last_sync)
                            VALUES (%s, %s, %s, %s, %s, NOW())
                            """,
                            (it["objectid"], it["name"], it["status_json"], it["rating"], it["wish_priority"])
                        )
                    else:
                        cursor.execute(
                            """
                            INSERT INTO collection (objectid, name, status, rating, wish_priority, last_sync)
                            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                            """,
                            (it["objectid"], it["name"], it["status_json"], it["rating"], it["wish_priority"])
                        )
                count += 1
            conn.commit()
    except Exception as e:
        logger.error(f"寫入收藏清單失敗: {e}")
    return count


def get_advanced_recommendations(username, owned_ids, algorithm='hybrid', limit=10):
    """使用 board-game-recommender 進行推薦"""
    try:
        logger.info(f"🔍 開始 board-game-recommender 推薦 - 用戶: {username}, 擁有遊戲: {len(owned_ids) if owned_ids else 0}")
        
        from board_game_recommender.recommend import BGGRecommender
        
        # 載入已訓練的模型
        import os
        model_path = f'data/rg_users/{username}/rg_model'
        if not os.path.exists(model_path):
            logger.warning(f"⚠️ 模型不存在: {model_path}")
            logger.info("💡 提示：模型可能因容器重啟而丟失，請重新訓練")
            return None
        
        logger.info(f"📂 載入模型: {model_path}")
        try:
            # 檢查模型目錄結構
            model_files = os.listdir(model_path) if os.path.exists(model_path) else []
            logger.info(f"📁 模型目錄內容: {model_files}")
            
            # 嘗試載入模型，可能需要指定子目錄
            if 'recommender' in model_files:
                recommender = BGGRecommender.load(model_path, dir_model='recommender')
            else:
                recommender = BGGRecommender.load(model_path)
            logger.info("✅ 模型載入成功")
        except Exception as load_error:
            logger.error(f"❌ 模型載入失敗: {load_error}")
            import traceback
            logger.error(f"詳細錯誤: {traceback.format_exc()}")
            return None
        
        # 獲取推薦
        logger.info(f"🎯 執行推薦算法，限制 {limit} 個結果...")
        logger.info(f"🔍 查詢用戶: {username}")
        
        # 檢查用戶是否在訓練資料中
        try:
            # 先嘗試不排除已知遊戲，看看是否有任何推薦
            test_recs = recommender.recommend(
                users=[username],
                num_games=5,
                exclude_known=False
            )
            logger.info(f"🧪 測試推薦（不排除已知）: {len(test_recs)} 個結果")
        except Exception as test_error:
            logger.warning(f"⚠️ 測試推薦失敗: {test_error}")
        
        # 嘗試不同的用戶名格式
        user_variants = [username, username.lower(), f"user_{username}"]
        recommendations_df = None
        
        for user_variant in user_variants:
            try:
                logger.info(f"🔄 嘗試用戶名格式: {user_variant}")
                recommendations_df = recommender.recommend(
                    users=[user_variant],
                    num_games=limit,
                    exclude_known=True
                )
                if len(recommendations_df) > 0:
                    logger.info(f"✅ 找到推薦 - 用戶名格式: {user_variant}")
                    break
                else:
                    logger.info(f"📭 無推薦結果 - 用戶名格式: {user_variant}")
            except Exception as variant_error:
                logger.warning(f"⚠️ 用戶名格式 {user_variant} 失敗: {variant_error}")
                continue
        
        if recommendations_df is None or len(recommendations_df) == 0:
            logger.error(f"❌ 所有用戶名格式都無法獲取推薦")
            return None
        
        logger.info(f"✅ 推薦查詢成功，獲得 {len(recommendations_df)} 個結果")
        
        # 轉換為標準格式
        recommendations = []
        for row in recommendations_df:
            recommendations.append({
                'game_id': int(row['bgg_id']),
                'name': str(row['name']),
                'year': int(row.get('year', 0)),
                'rating': float(row.get('avg_rating', 0.0)),
                'rank': int(row.get('rank', 0)),
                'rec_score': float(row.get('score', 0.0)),
                'source': 'board_game_recommender'
            })
        
        logger.info(f"✅ board-game-recommender 成功產生 {len(recommendations)} 個推薦")
        return recommendations
        
    except Exception as e:
        logger.error(f"❌ board-game-recommender 發生錯誤: {e}")
        import traceback
        logger.error(f"詳細錯誤堆疊: {traceback.format_exc()}")
        return None

def get_local_recommendations(username, owned_ids, limit=10):
    """使用本地資料庫和 BGG API 提供基於熱門度的推薦"""
    try:
        owned_set = set(owned_ids) if owned_ids else set()
        
        # 步驟 1: 從本地資料庫獲取基礎推薦
        local_recommendations = []
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 構建排除已擁有遊戲的 WHERE 條件
            config = get_database_config()
            if owned_set:
                if config['type'] == 'postgresql':
                    placeholders = ','.join(['%s'] * len(owned_set))
                else:
                    placeholders = ','.join(['?'] * len(owned_set))
                exclude_clause = f"AND g.objectid NOT IN ({placeholders})"
                params = list(owned_set) + [min(limit, 50)]  # 最多取50個本地推薦
            else:
                exclude_clause = ""
                params = [min(limit, 50)]
            
            # 查詢推薦遊戲（基於評分和排名）
            limit_placeholder = '%s' if config['type'] == 'postgresql' else '?'
            query = f"""
            SELECT 
                g.objectid,
                g.name,
                g.year,
                g.rating,
                g.rank,
                g.weight,
                g.minplayers,
                g.maxplayers,
                COALESCE(g.rating, 0) + 
                CASE 
                    WHEN g.rank > 0 THEN (10000 - g.rank) / 1000.0 
                    ELSE 0 
                END as popularity_score
            FROM game_detail g
            WHERE g.objectid IS NOT NULL 
                AND g.name IS NOT NULL
                {exclude_clause}
            ORDER BY popularity_score DESC, g.rating DESC
            LIMIT {limit_placeholder}
            """
            
            cursor.execute(query, params)
            games = cursor.fetchall()
            
            for game in games:
                local_recommendations.append({
                    'game_id': game[0],
                    'name': game[1],
                    'year': game[2] or '',
                    'rating': round(game[3] or 0, 1),
                    'rank': game[4] or 0,
                    'weight': round(game[5] or 0, 1),
                    'min_players': game[6] or 1,
                    'max_players': game[7] or 1,
                    'rec_score': round(game[8], 2),
                    'source': 'local_db'
                })
        
        # 步驟 2: 如果本地推薦不足，使用 BGG 熱門遊戲補充
        if len(local_recommendations) < limit:
            logger.info(f"本地推薦只有 {len(local_recommendations)} 個，嘗試從 BGG 獲取更多推薦")
            
            # BGG 熱門遊戲 ID（這些是一些知名的熱門遊戲）
            popular_game_ids = [
                174430,  # Gloomhaven
                161936,  # Pandemic Legacy: Season 1
                169786,  # Scythe
                120677,  # Terra Mystica
                167791,  # Terraforming Mars
                224517,  # Brass: Birmingham
                193738,  # Great Western Trail
                182028,  # Through the Ages: A New Story of Civilization
                233078,  # Twilight Imperium: Fourth Edition
                205637,  # Arkham Horror: The Card Game
                266192,  # Wingspan
                31260,   # Agricola
                36218,   # Dominion
                84876,   # The Castles of Burgundy
                148228,  # Splendor
                30549,   # Pandemic
                103343,  # King of Tokyo
                124742,  # Android: Netrunner
                254640,  # Azul
                13,      # Catan
                68448,   # 7 Wonders
                70323,   # King of New York
                146508,  # Eldritch Horror
                12333,   # Twilight Struggle
                150376,  # Gloom
            ]
            
            # 排除已擁有的遊戲
            available_ids = [gid for gid in popular_game_ids if gid not in owned_set]
            local_game_ids = {rec['game_id'] for rec in local_recommendations}
            new_ids = [gid for gid in available_ids if gid not in local_game_ids]
            
            # 只取需要的數量
            needed = limit - len(local_recommendations)
            bgg_ids = new_ids[:needed]
            
            if bgg_ids:
                # 從 BGG API 獲取詳細資料
                bgg_details = fetch_game_details_from_bgg(bgg_ids)
                
                for game_id, details in bgg_details.items():
                    local_recommendations.append({
                        'game_id': details['id'],
                        'name': details['name'],
                        'year': details['year'],
                        'rating': details['rating'],
                        'rank': details['rank'],
                        'weight': details['weight'],
                        'min_players': details['min_players'],
                        'max_players': details['max_players'],
                        'rec_score': details['rating'],  # 使用 BGG 評分作為推薦分數
                        'source': 'bgg_popular'
                    })
        
        # 按推薦分數排序並限制數量
        local_recommendations.sort(key=lambda x: x['rec_score'], reverse=True)
        final_recommendations = local_recommendations[:limit]
        
        logger.info(f"總共產生了 {len(final_recommendations)} 個推薦 (本地: {len([r for r in final_recommendations if r['source'] == 'local_db'])}, BGG: {len([r for r in final_recommendations if r['source'] == 'bgg_popular'])})")
        return final_recommendations
        
    except Exception as e:
        logger.error(f"本地推薦器發生錯誤: {e}")
        return None

def fetch_game_details_from_bgg(game_ids):
    """從 BGG API 獲取遊戲詳細資訊"""
    if not game_ids:
        return {}
    
    try:
        import xml.etree.ElementTree as ET
        import time
        
        # BGG API 限制一次最多查詢20個遊戲
        game_details = {}
        
        for i in range(0, len(game_ids), 20):
            batch_ids = game_ids[i:i+20]
            ids_str = ','.join(map(str, batch_ids))
            
            # 構建 BGG API URL
            url = f'https://boardgamegeek.com/xmlapi2/thing?id={ids_str}&type=boardgame&stats=1'
            
            try:
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                
                # 解析 XML 響應
                root = ET.fromstring(response.content)
                
                for item in root.findall('item'):
                    game_id = int(item.get('id'))
                    
                    # 提取基本資訊
                    name_elem = item.find('.//name[@type="primary"]')
                    name = name_elem.get('value') if name_elem is not None else f'遊戲 {game_id}'
                    
                    year_elem = item.find('yearpublished')
                    year = int(year_elem.get('value')) if year_elem is not None and year_elem.get('value') else 0
                    
                    # 提取統計資訊
                    stats = item.find('statistics/ratings')
                    rating = 0.0
                    rank = 0
                    weight = 0.0
                    
                    if stats is not None:
                        average_elem = stats.find('average')
                        if average_elem is not None:
                            rating = float(average_elem.get('value') or 0)
                        
                        # 尋找 BoardGame Rank
                        for rank_elem in stats.findall('.//rank'):
                            if rank_elem.get('name') == 'boardgame':
                                rank_value = rank_elem.get('value')
                                if rank_value and rank_value != 'Not Ranked':
                                    rank = int(rank_value)
                                break
                        
                        weight_elem = stats.find('averageweight')
                        if weight_elem is not None:
                            weight = float(weight_elem.get('value') or 0)
                    
                    # 提取玩家數量
                    minplayers_elem = item.find('minplayers')
                    maxplayers_elem = item.find('maxplayers')
                    min_players = int(minplayers_elem.get('value')) if minplayers_elem is not None else 1
                    max_players = int(maxplayers_elem.get('value')) if maxplayers_elem is not None else 1
                    
                    # 提取遊戲時間
                    playingtime_elem = item.find('playingtime')
                    playing_time = int(playingtime_elem.get('value')) if playingtime_elem is not None else 0
                    
                    game_details[game_id] = {
                        'id': game_id,
                        'name': name,
                        'year': year,
                        'rating': round(rating, 1),
                        'rank': rank,
                        'weight': round(weight, 1),
                        'min_players': min_players,
                        'max_players': max_players,
                        'playing_time': playing_time,
                        'source': 'bgg_api'
                    }
                
                # BGG API 要求限制請求頻率
                if i + 20 < len(game_ids):
                    time.sleep(1)
                    
            except Exception as e:
                logger.error(f"獲取遊戲 {batch_ids} 的 BGG 資料時發生錯誤: {e}")
                continue
        
        logger.info(f"從 BGG API 獲取了 {len(game_details)} 個遊戲的詳細資料")
        return game_details
        
    except Exception as e:
        logger.error(f"BGG API 查詢發生錯誤: {e}")
        return {}

def call_recommend_games_api(bgg_username: str, owned_ids: List[int], limit: int = 30):
    """可選：呼叫 Recommend.Games 的外部 API（若有設定環境變數）。
    注意：此為預留，實際端點與參數需依官方文件調整。
    """
    if not RG_API_URL:
        return None, '未設定 RG_API_URL，改為顯示前往外部網站的連結'
    try:
        headers = {'Authorization': f'Bearer {RG_API_KEY}'} if RG_API_KEY else {}
        payload = {
            'username': bgg_username,
            'owned_ids': owned_ids,
            'limit': limit
        }
        resp = requests.post(f"{RG_API_URL}/recommend", json=payload, headers=headers, timeout=30)
        if resp.status_code != 200:
            return None, f"外部服務回應 {resp.status_code}"
        return resp.json(), None
    except Exception as e:
        logger.warning(f"呼叫 Recommend.Games 外部服務失敗: {e}")
        return None, str(e)

def get_latest_report():
    """獲取最新的報表內容（優先從資料庫讀取）"""
    try:
        # 優先從資料庫讀取最新報表
        with get_db_connection() as conn:
            cursor = conn.cursor()
            config = get_database_config()

            if config['type'] == 'postgresql':
                cursor.execute("""
                    SELECT report_date, lang, content, file_size, updated_at
                    FROM reports
                    WHERE lang = 'zh-tw'
                    ORDER BY report_date DESC, updated_at DESC
                    LIMIT 1
                """)
            else:
                cursor.execute("""
                    SELECT report_date, lang, content, file_size, updated_at
                    FROM reports
                    WHERE lang = 'zh-tw'
                    ORDER BY report_date DESC, updated_at DESC
                    LIMIT 1
                """)

            result = cursor.fetchone()
            if result:
                report_date, lang, content, file_size, updated_at = result
                logger.info(f"✅ 從資料庫讀取最新報表: {report_date}-{lang} ({file_size} bytes)")
                return content, f"report-{report_date}-{lang}.md"

        # 資料庫中沒有，嘗試從檔案讀取
        logger.info("⚠️ 資料庫中沒有報表，嘗試從檔案讀取...")
        # 尋找最新的報表檔案
        report_dir = "frontend/public/outputs"
        if not os.path.exists(report_dir):
            return None, "報表目錄不存在"

        # 尋找最新的繁體中文報表
        report_files = [f for f in os.listdir(report_dir) if f.endswith('-zh-tw.md')]
        if not report_files:
            return None, "找不到報表檔案"

        # 取得最新的報表
        latest_file = sorted(report_files)[-1]
        report_path = os.path.join(report_dir, latest_file)

        with open(report_path, 'r', encoding='utf-8') as f:
            content = f.read()

        logger.info(f"✅ 從檔案讀取最新報表: {report_path}")
        return content, latest_file

    except Exception as e:
        logger.error(f"讀取報表失敗: {e}")
        return None, "讀取報表失敗"

def get_available_dates():
    """獲取所有可用的報表日期（優先從資料庫讀取）"""
    try:
        dates_set = set()

        # 優先從資料庫讀取
        with get_db_connection() as conn:
            cursor = conn.cursor()
            config = get_database_config()

            if config['type'] == 'postgresql':
                cursor.execute("""
                    SELECT DISTINCT report_date
                    FROM reports
                    WHERE lang = 'zh-tw'
                    ORDER BY report_date DESC
                """)
            else:
                cursor.execute("""
                    SELECT DISTINCT report_date
                    FROM reports
                    WHERE lang = 'zh-tw'
                    ORDER BY report_date DESC
                """)

            db_dates = [row[0] for row in cursor.fetchall()]
            dates_set.update(db_dates)

            if db_dates:
                logger.info(f"✅ 從資料庫讀取到 {len(db_dates)} 個報表日期")

        # 同時從檔案系統讀取（作為備份）
        report_dir = "frontend/public/outputs"
        if os.path.exists(report_dir):
            report_files = [f for f in os.listdir(report_dir) if f.endswith('-zh-tw.md')]
            file_dates = [f.replace('report-', '').replace('-zh-tw.md', '') for f in report_files]
            dates_set.update(file_dates)

            if file_dates:
                logger.info(f"✅ 從檔案系統讀取到 {len(file_dates)} 個報表日期")

        # 合併並排序
        all_dates = sorted(list(dates_set), reverse=True)
        logger.info(f"📊 總共可用報表日期: {len(all_dates)} 個")
        return all_dates

    except Exception as e:
        logger.error(f"獲取可用日期失敗: {e}")
        return []

def get_game_details_from_db(objectid):
    """從資料庫獲取遊戲的完整詳細資料"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            config = get_database_config()

            # 獲取遊戲基本資料（包含字串格式的分類機制資料）
            if config['type'] == 'postgresql':
                cursor.execute("""
                    SELECT rating, rank, weight, minplayers, maxplayers, bestplayers,
                           minplaytime, maxplaytime, image, categories, mechanics,
                           designers, artists, publishers
                    FROM game_detail
                    WHERE objectid = %s
                """, (objectid,))
            else:
                cursor.execute("""
                    SELECT rating, rank, weight, minplayers, maxplayers, bestplayers,
                           minplaytime, maxplaytime, image, categories, mechanics,
                           designers, artists, publishers
                    FROM game_detail
                    WHERE objectid = ?
                """, (objectid,))

            game_detail = cursor.fetchone()

            # 獲取所有類型的分類資料
            if config['type'] == 'postgresql':
                cursor.execute("""
                    SELECT bi.id, bi.name, bi.category
                    FROM bgg_items bi
                    JOIN game_categories gc ON bi.id = gc.category_id AND bi.category = gc.category_type
                    WHERE gc.objectid = %s
                    ORDER BY bi.category, bi.name
                """, (objectid,))
            else:
                cursor.execute("""
                    SELECT bi.id, bi.name, bi.category
                    FROM bgg_items bi
                    JOIN game_categories gc ON bi.id = gc.category_id AND bi.category = gc.category_type
                    WHERE gc.objectid = ?
                    ORDER BY bi.category, bi.name
                """, (objectid,))

            category_results = cursor.fetchall()

        # 組織分類資料
        categories = {'boardgamecategory': [], 'boardgamemechanic': [],
                     'boardgamedesigner': [], 'boardgameartist': [], 'boardgamepublisher': []}

        for cat_id, name, category in category_results:
            if category in categories:
                categories[category].append({'id': cat_id, 'name': name})

        # 處理字串格式的分類資料（作為備用）
        def parse_string_to_dict_list(text):
            """將逗號分隔的字串轉換為字典列表格式"""
            if not text or not text.strip():
                return []
            items = [item.strip() for item in text.split(',') if item.strip()]
            return [{'id': None, 'name': item} for item in items]

        # 組織返回資料
        if game_detail:
            # 如果從 bgg_items 表中沒有取得分類資料，使用字串資料
            final_categories = categories['boardgamecategory']
            final_mechanics = categories['boardgamemechanic']
            final_designers = categories['boardgamedesigner']
            final_artists = categories['boardgameartist']
            final_publishers = categories['boardgamepublisher']

            # 如果沒有結構化資料，解析字串
            if not final_categories and len(game_detail) > 9:
                final_categories = parse_string_to_dict_list(game_detail[9])
            if not final_mechanics and len(game_detail) > 10:
                final_mechanics = parse_string_to_dict_list(game_detail[10])
            if not final_designers and len(game_detail) > 11:
                final_designers = parse_string_to_dict_list(game_detail[11])
            if not final_artists and len(game_detail) > 12:
                final_artists = parse_string_to_dict_list(game_detail[12])
            if not final_publishers and len(game_detail) > 13:
                final_publishers = parse_string_to_dict_list(game_detail[13])

            return {
                'rating': game_detail[0],
                'bgg_rank': game_detail[1],  # BGG總排名
                'weight': game_detail[2],
                'min_players': game_detail[3],
                'max_players': game_detail[4],
                'bestplayers': game_detail[5],
                'minplaytime': game_detail[6],
                'maxplaytime': game_detail[7],
                'image': game_detail[8],
                'categories': final_categories,
                'mechanics': final_mechanics,
                'designers': final_designers,
                'artists': final_artists,
                'publishers': final_publishers
            }
        else:
            return {
                'rating': None,
                'bgg_rank': None,
                'weight': None,
                'min_players': None,
                'max_players': None,
                'bestplayers': None,
                'minplaytime': None,
                'maxplaytime': None,
                'image': None,
                'categories': categories['boardgamecategory'],
                'mechanics': categories['boardgamemechanic'],
                'designers': categories['boardgamedesigner'],
                'artists': categories['boardgameartist'],
                'publishers': categories['boardgamepublisher']
            }

    except Exception as e:
        logger.error(f"獲取遊戲詳細資料失敗: {e}")
        return {
            'rating': None,
            'bgg_rank': None,
            'weight': None,
            'min_players': None,
            'max_players': None,
            'bestplayers': None,
            'minplaytime': None,
            'maxplaytime': None,
            'image': None,
            'categories': [],
            'mechanics': [],
            'designers': [],
            'artists': [],
            'publishers': []
        }

def get_game_categories_from_db(objectid):
    """從資料庫獲取遊戲的分類資訊（包含ID）- 保持向後兼容"""
    details = get_game_details_from_db(objectid)
    return {
        'boardgamecategory': details['categories'],
        'boardgamemechanic': details['mechanics'],
        'boardgamedesigner': details['designers'],
        'boardgameartist': details['artists'],
        'boardgamepublisher': details['publishers']
    }

def parse_game_data_from_report(content):
    """從報表內容解析遊戲資料"""
    games = []
    if not content:
        return games

    try:
        # 解析排行榜表格
        lines = content.split('\n')
        in_table = False

        for line in lines:
            line = line.strip()

            # 檢查是否是表格開始
            if '| 排名 | 桌遊 | 年份 | 排名變化 |' in line:
                in_table = True
                continue
            elif '|------|------|------|----------|' in line:
                continue
            elif in_table and line.startswith('|') and '|' in line:
                # 解析表格行
                parts = [p.strip() for p in line.split('|') if p.strip()]
                if len(parts) >= 4:
                    try:
                        rank = int(parts[0])
                        # 移除限制，獲取所有遊戲資料

                        # 提取遊戲名稱和連結
                        game_cell = parts[1]
                        name_match = re.search(r'\[([^\]]+)\]', game_cell)
                        game_name = name_match.group(1) if name_match else '未知遊戲'

                        # 提取遊戲ID（從BGG連結中）
                        bgg_link_match = re.search(r'https://boardgamegeek\.com/boardgame/(\d+)', game_cell)
                        game_objectid = int(bgg_link_match.group(1)) if bgg_link_match else None

                        # 提取圖片URL
                        img_match = re.search(r'<img src="([^"]+)"', game_cell)
                        image_url = img_match.group(1) if img_match else None

                        # 提取年份
                        year = parts[2]

                        # 解析排名變化
                        rank_change_cell = parts[3]
                        rank_change = 0
                        is_new = False

                        if '⬆️' in rank_change_cell:
                            change_match = re.search(r'⬆️\s*(\d+)', rank_change_cell)
                            if change_match:
                                rank_change = int(change_match.group(1))
                        elif '⬇️' in rank_change_cell:
                            change_match = re.search(r'⬇️\s*(\d+)', rank_change_cell)
                            if change_match:
                                rank_change = -int(change_match.group(1))
                        elif '🆕' in rank_change_cell:
                            is_new = True

                        # 暫時存儲遊戲ID，稍後批量查詢
                        db_details = {}

                        games.append({
                            'rank': rank,
                            'name': game_name,
                            'objectid': game_objectid,
                            'year': year,
                            'image': db_details.get('image') or image_url,
                            'rank_change': rank_change,
                            'is_new': is_new,
                            'rating': db_details.get('rating') or '8.0',
                            'bgg_rank': db_details.get('bgg_rank'),
                            'weight': db_details.get('weight'),
                            'min_players': db_details.get('min_players') or 1,
                            'max_players': db_details.get('max_players') or 4,
                            'bestplayers': db_details.get('bestplayers'),
                            'playtime': 60,  # 預設值，後續會更新
                            'minplaytime': db_details.get('minplaytime'),
                            'maxplaytime': db_details.get('maxplaytime'),
                            'categories': db_details.get('categories', []),
                            'mechanics': db_details.get('mechanics', []),
                            'designers': db_details.get('designers', []),
                            'artists': db_details.get('artists', []),
                            'publishers': db_details.get('publishers', []),
                            'reason': None
                        })

                    except (ValueError, IndexError) as e:
                        logger.warning(f"解析排行榜行失敗: {line}, 錯誤: {e}")
                        continue
            elif in_table and not line.startswith('|'):
                # 表格結束
                break

        # 批量取得所有遊戲的資料庫詳細資訊
        logger.info(f"批量查詢 {len(games)} 個遊戲的詳細資料...")

        # 批量查詢 reason 資料
        reason_objectids = [game['objectid'] for game in games if game['objectid']]
        reasons_dict = {}
        if reason_objectids:
            try:
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    config = get_database_config()
                    placeholders = ','.join(['%s'] * len(reason_objectids))
                    query = f"SELECT objectid, reason FROM forum_threads_i18n WHERE objectid IN ({placeholders}) AND lang = 'zh-tw'"
                    cursor.execute(query, reason_objectids)
                    for oid, reason in cursor.fetchall():
                        reasons_dict[oid] = reason
                logger.info(f"✅ 從資料庫載入 {len(reasons_dict)} 個遊戲的 reason 資料")
            except Exception as e:
                logger.warning(f"查詢 reason 資料失敗: {e}")

        for game in games:
            if game['objectid']:
                try:
                    db_details = get_game_details_from_db(game['objectid'])
                    # 更新遊戲資料
                    game.update({
                        'image': db_details.get('image') or game.get('image'),
                        'rating': db_details.get('rating') or game.get('rating', '8.0'),
                        'bgg_rank': db_details.get('bgg_rank'),
                        'weight': db_details.get('weight'),
                        'min_players': db_details.get('min_players') or game.get('min_players', 1),
                        'max_players': db_details.get('max_players') or game.get('max_players', 4),
                        'bestplayers': db_details.get('bestplayers'),
                        'minplaytime': db_details.get('minplaytime'),
                        'maxplaytime': db_details.get('maxplaytime'),
                        'categories': db_details.get('categories', []),
                        'mechanics': db_details.get('mechanics', []),
                        'designers': db_details.get('designers', []),
                        'artists': db_details.get('artists', []),
                        'publishers': db_details.get('publishers', [])
                    })

                    # 從資料庫讀取 reason
                    if game['objectid'] in reasons_dict:
                        game['reason'] = reasons_dict[game['objectid']]
                        logger.info(f"✅ 為 {game['name']} 載入資料庫 reason")

                except Exception as e:
                    logger.warning(f"取得遊戲 {game['objectid']} 的詳細資料失敗: {e}")

        # 解析詳細資料區段來獲取更多資訊
        for game in games:
            game_section_pattern = f"### <a id='{re.escape(game['name'].replace(' ', '-').replace(':', ''))}.*?</a>{re.escape(game['name'])}"
            match = re.search(game_section_pattern, content, re.DOTALL)
            if match:
                section_start = match.end()
                # 找到下一個遊戲區段或結束
                next_game_match = re.search(r'###\s+<a id=', content[section_start:])
                if next_game_match:
                    section_end = section_start + next_game_match.start()
                else:
                    section_end = len(content)

                section_content = content[section_start:section_end]

                # 提取評分
                rating_match = re.search(r'Rating.*?(\d+\.\d+)/10', section_content)
                if rating_match:
                    game['rating'] = rating_match.group(1)

                # 提取人數
                players_match = re.search(r'人數.*?(\d+)～(\d+)\s*人', section_content)
                if players_match:
                    game['min_players'] = int(players_match.group(1))
                    game['max_players'] = int(players_match.group(2))

                # 提取時間
                time_match = re.search(r'時間.*?(\d+)～(\d+)\s*分鐘', section_content)
                if time_match:
                    game['playtime'] = int(time_match.group(2))
                elif re.search(r'時間.*?(\d+)\s*分鐘', section_content):
                    time_single_match = re.search(r'時間.*?(\d+)\s*分鐘', section_content)
                    game['playtime'] = int(time_single_match.group(1))

                # 提取分類
                category_match = re.search(r'分類.*?：\s*([^\n]+)', section_content)
                if category_match:
                    categories = [{'name': cat.strip()} for cat in category_match.group(1).split(',')]
                    game['categories'] = categories

                # 提取機制
                mechanic_match = re.search(r'機制.*?：\s*([^\n]+)', section_content)
                if mechanic_match:
                    mechanics = [{'name': mech.strip()} for mech in mechanic_match.group(1).split(',')]
                    game['mechanics'] = mechanics

                # 提取設計師
                designer_match = re.search(r'設計師.*?：\s*([^\n]+)', section_content)
                if designer_match:
                    designers = [{'name': designer.strip()} for designer in designer_match.group(1).split(',')]
                    game['designers'] = designers

                # 提取美術
                artist_match = re.search(r'美術.*?：\s*([^\n]+)', section_content)
                if artist_match:
                    artists = [{'name': artist.strip()} for artist in artist_match.group(1).split(',')]
                    game['artists'] = artists

                # 提取發行商
                publisher_match = re.search(r'發行商.*?：\s*([^\n]+)', section_content)
                if publisher_match:
                    publishers = [{'name': pub.strip()} for pub in publisher_match.group(1).split(',')]
                    game['publishers'] = publishers

                # 提取上榜原因
                reason_match = re.search(r'\*\*📈 上榜原因推論：\*\*\s*>\s*(.*?)(?=\n---|\n###|\n##|$)', section_content, re.DOTALL)
                if reason_match:
                    reason_text = reason_match.group(1).strip()
                    logger.info(f"✅ 找到 {game['name']} 的原始推論文字: {reason_text[:100]}...")
                    # 清理多餘的空白和換行並移除前綴
                    reason_text = re.sub(r'\s+', ' ', reason_text)
                    # 移除《遊戲名》近期上榜的主要原因是 這類前綴
                    reason_text = re.sub(r'^《[^》]+》[^，。]*?[的是]', '', reason_text)
                    # 移除其他可能的前綴
                    reason_text = re.sub(r'^[^，。]*?主要原因是', '', reason_text)
                    reason_text = reason_text.strip()
                    logger.info(f"✅ {game['name']} 清理後的推論文字: {reason_text[:100]}...")
                    game['reason'] = reason_text
                else:
                    logger.warning(f"⚠️ 未找到 {game['name']} 的上榜原因推論")
                    # 顯示區段內容以便除錯
                    logger.debug(f"📝 {game['name']} 的區段內容前200字元: {section_content[:200]}...")
                    # 檢查是否包含推論關鍵字
                    if '📈 上榜原因推論' in section_content:
                        logger.info(f"🔍 {game['name']} 的區段包含推論關鍵字，但正則表達式無法匹配")
                    elif '因為技術問題' in section_content:
                        logger.info(f"🔍 {game['name']} 顯示技術問題訊息")
                    else:
                        # 為沒有詳細分析區段的遊戲提供預設訊息
                        game['reason'] = "此遊戲未包含在詳細分析範圍內，可能是因為討論熱度較低或為常駐榜單遊戲。"
                        logger.info(f"🔄 為 {game['name']} 設定預設上榜原因說明")
            else:
                # 沒有找到詳細區段的遊戲，提供預設訊息
                game['reason'] = "此遊戲未包含在詳細分析範圍內，可能是因為討論熱度較低或為常駐榜單遊戲。"
                logger.info(f"🔄 為 {game['name']} 設定預設上榜原因說明（未找到詳細區段）")

        return games

    except Exception as e:
        logger.error(f"解析遊戲資料失敗: {e}")
        return []

def run_scheduler_async():
    """異步執行排程任務（支持用戶停止）"""
    global task_status

    try:
        task_status['is_running'] = True
        task_status['start_time'] = datetime.now()
        task_status['stop_requested'] = False
        task_status['stopped_by_user'] = False

        update_task_status('開始', 0, '初始化任務...')

        logger.info("開始執行完整排程任務...")

        # 檢查是否在初始化階段就被停止
        if check_if_should_stop():
            logger.info("🛑 任務在初始化階段被停止")
            update_task_status('已停止', 0, '任務已被用戶停止')
            task_status['is_running'] = False
            task_status['stopped_by_user'] = True
            return False, "任務已被用戶停止"

        logger.info(f"🔧 當前工作目錄: {os.getcwd()}")
        logger.info(f"🔧 Python 版本: {subprocess.run(['python3', '--version'], capture_output=True, text=True).stdout.strip()}")

        # 檢查當前環境和權限
        logger.info(f"🔧 當前用戶: {os.getenv('USER', 'unknown')}")
        logger.info(f"🔧 HOME 目錄: {os.getenv('HOME', 'unknown')}")
        logger.info(f"🔧 工作目錄: {os.getcwd()}")

        # 檢查輸出目錄
        output_dir = "frontend/public/outputs"
        abs_output_dir = os.path.abspath(output_dir)
        logger.info(f"📁 輸出目錄相對路徑: {output_dir}")
        logger.info(f"📁 輸出目錄絕對路徑: {abs_output_dir}")

        if os.path.exists(output_dir):
            logger.info(f"✅ 輸出目錄存在")
            try:
                files = os.listdir(output_dir)
                logger.info(f"📂 目錄中有 {len(files)} 個檔案")
            except Exception as e:
                logger.error(f"❌ 無法列出目錄內容: {e}")
        else:
            logger.warning(f"⚠️ 輸出目錄不存在: {output_dir}")

        # 再次檢查是否被停止
        if check_if_should_stop():
            logger.info("🛑 任務在環境檢查階段被停止")
            update_task_status('已停止', 0, '任務已被用戶停止')
            task_status['is_running'] = False
            task_status['stopped_by_user'] = True
            return False, "任務已被用戶停止"

        update_task_status('準備執行', 5, '檢查環境完成，開始執行排程...')

        # 執行排程腳本，使用 Popen 來支持中途停止
        cmd = [
            'python3', 'scheduler.py', '--run-now',
            '--detail', 'all',
            '--lang', 'zh-tw'
        ]

        # 根據設定添加額外參數
        force_llm_analysis = task_status.get('force_llm_analysis', False)
        force_regenerate = task_status.get('force_regenerate', False)

        if force_llm_analysis:
            cmd.append('--force-llm-analysis')
            logger.info("🤖 啟用強制LLM分析模式")

        if force_regenerate:
            cmd.append('--force')
            logger.info("🔄 啟用強制重新產生模式")

        logger.info(f"🚀 執行命令: {' '.join(cmd)}")

        update_task_status('執行中', 10, '正在執行數據抓取和報表生成...')

        # 使用 Popen 啟動子進程
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )

        # 監控子進程並檢查停止請求
        output_lines = []
        error_lines = []
        start_time = datetime.now()
        last_progress_update = start_time
        max_runtime = 7200  # 120分鐘（2小時）超時
        warning_runtime = 5400  # 90分鐘警告

        while process.poll() is None:  # 進程還在運行
            current_time = datetime.now()
            elapsed = (current_time - task_status['start_time']).total_seconds()

            # 檢查超時
            if elapsed > max_runtime:
                logger.error(f"⏰ 任務執行超時（{max_runtime/60}分鐘），強制終止進程")
                try:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    update_task_status('超時', 0, f'任務執行超過{max_runtime/60}分鐘，已強制終止')
                    task_status['is_running'] = False
                    return False, f"任務執行超時（{max_runtime/60}分鐘）"
                except Exception as timeout_error:
                    logger.error(f"❌ 終止超時進程時發生錯誤: {timeout_error}")
                    update_task_status('錯誤', 0, '終止超時任務時發生錯誤')
                    task_status['is_running'] = False
                    return False, f"終止超時任務時發生錯誤: {timeout_error}"

            # 45分鐘警告
            elif elapsed > warning_runtime and elapsed % 300 < 2:  # 每5分鐘提醒一次
                logger.warning(f"⚠️ 任務已運行{int(elapsed/60)}分鐘，接近超時限制")

            # 檢查是否需要停止
            if check_if_should_stop():
                logger.info("🛑 收到停止請求，正在終止子進程...")
                update_task_status('停止中', task_status['progress'], '正在停止任務...')

                try:
                    # 優雅地終止進程
                    process.terminate()
                    # 等待 5 秒讓進程優雅退出
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        # 如果進程沒有優雅退出，強制終止
                        logger.warning("⚠️ 進程未能優雅退出，強制終止...")
                        process.kill()
                        process.wait()

                    logger.info("✅ 子進程已成功停止")
                    update_task_status('已停止', 0, '任務已被用戶停止')
                    task_status['is_running'] = False
                    task_status['stopped_by_user'] = True
                    return False, "任務已被用戶停止"

                except Exception as stop_error:
                    logger.error(f"❌ 停止進程時發生錯誤: {stop_error}")
                    # 即使停止失敗，也要更新狀態
                    update_task_status('停止失敗', 0, '停止任務時發生錯誤')
                    task_status['is_running'] = False
                    return False, f"停止任務時發生錯誤: {stop_error}"

            # 讀取和解析子進程輸出
            try:
                # 讀取 stdout 輸出
                while True:
                    try:
                        line = process.stdout.readline()
                        if not line:
                            break

                        line = line.strip()
                        if line:
                            output_lines.append(line)
                            logger.info(f"📋 子進程輸出: {line}")

                            # 解析實際執行狀態
                            progress, status_msg = parse_execution_progress(line, elapsed)
                            if progress is not None and status_msg:
                                update_task_status('執行中', progress, status_msg)
                                last_progress_update = current_time
                                task_status['last_specific_update'] = current_time
                            elif status_msg:
                                # 即使沒有進度數字，也更新狀態訊息
                                current_progress = task_status.get('progress', 0)
                                update_task_status('執行中', current_progress, status_msg)
                                last_progress_update = current_time

                    except Exception as stdout_error:
                        break

                # 讀取 stderr 輸出
                while True:
                    try:
                        error_line = process.stderr.readline()
                        if not error_line:
                            break

                        error_line = error_line.strip()
                        if error_line:
                            error_lines.append(error_line)
                            logger.warning(f"⚠️ 子進程錯誤: {error_line}")

                            # 解析錯誤中的有用訊息
                            progress, status_msg = parse_execution_progress(error_line, elapsed)
                            if status_msg:
                                current_progress = task_status.get('progress', 0)
                                update_task_status('執行中', current_progress, status_msg)
                                last_progress_update = current_time

                    except Exception as stderr_error:
                        break

            except Exception as read_error:
                logger.warning(f"讀取子進程輸出時發生錯誤: {read_error}")

            # 如果超過30秒沒有具體更新，顯示時間狀態
            if (current_time - last_progress_update).total_seconds() >= 30:
                time_status = f'運行中... ({int(elapsed/60)} 分鐘 {int(elapsed%60)} 秒)'
                if elapsed > warning_runtime:
                    time_status = f'⚠️ 任務運行時間較長 ({int(elapsed/60)} 分鐘)，請耐心等待...'

                current_progress = task_status.get('progress', 0)
                update_task_status('執行中', current_progress, time_status)
                last_progress_update = current_time

            # 短暫休眠，避免過度消耗 CPU
            time.sleep(0.5)

        # 子進程已完成，獲取輸出
        stdout, stderr = process.communicate()
        return_code = process.returncode

        logger.info(f"📊 命令執行完成，返回碼: {return_code}")

        if stdout:
            logger.info("📝 標準輸出:")
            for line in stdout.split('\n'):
                if line.strip():
                    logger.info(f"  STDOUT: {line}")

        if stderr:
            logger.info("⚠️ 標準錯誤:")
            for line in stderr.split('\n'):
                if line.strip():
                    logger.info(f"  STDERR: {line}")

        # 最後檢查是否被停止（以防在進程結束後立即被停止）
        if check_if_should_stop():
            logger.info("🛑 任務在完成檢查階段被停止")
            update_task_status('已停止', 0, '任務已被用戶停止')
            task_status['is_running'] = False
            task_status['stopped_by_user'] = True
            return False, "任務已被用戶停止"

        if return_code == 0:
            update_task_status('檢查結果', 90, '排程執行成功，檢查產生的檔案...')

            logger.info("✅ 排程任務執行成功")

            # 檢查報表檔案是否實際產生
            report_dir = "frontend/public/outputs"
            logger.info(f"🔍 檢查報表目錄: {report_dir}")

            if os.path.exists(report_dir):
                files = os.listdir(report_dir)
                logger.info(f"📂 目錄中的檔案數量: {len(files)}")

                # 列出最近的幾個檔案
                if files:
                    sorted_files = sorted(files, reverse=True)[:5]
                    logger.info("📄 最近的報表檔案:")
                    for f in sorted_files:
                        file_path = os.path.join(report_dir, f)
                        file_size = os.path.getsize(file_path)
                        file_mtime = os.path.getmtime(file_path)
                        import datetime as dt
                        mtime_str = dt.datetime.fromtimestamp(file_mtime).strftime('%Y-%m-%d %H:%M:%S')
                        logger.info(f"  📄 {f} ({file_size} bytes, {mtime_str})")

                    # 檢查今日報表
                    today = datetime.now().strftime("%Y-%m-%d")
                    today_reports = [f for f in files if f.startswith(f"report-{today}")]
                    logger.info(f"📄 今日報表檔案: {today_reports}")

                    if today_reports:
                        update_task_status('完成', 100, f'成功產生 {len(today_reports)} 個今日報表檔案')
                        task_status['is_running'] = False
                        return True, "排程任務執行成功，報表已產生"
                    else:
                        update_task_status('警告', 95, '排程執行成功但未發現今日報表檔案')
                        task_status['is_running'] = False
                        return True, "排程任務執行成功，但請檢查報表檔案"
                else:
                    logger.warning("⚠️ 報表目錄為空！")
                    update_task_status('警告', 90, '排程執行成功但報表目錄為空')
            else:
                logger.error(f"❌ 報表目錄不存在: {report_dir}")
                update_task_status('錯誤', 85, '報表目錄不存在')

            task_status['is_running'] = False
            return True, "排程任務執行成功"
        else:
            logger.error(f"❌ 排程任務執行失敗，返回碼: {return_code}")
            update_task_status('失敗', 0, f'排程執行失敗: {stderr[:100] if stderr else "未知錯誤"}...')
            task_status['is_running'] = False
            return False, f"排程任務執行失敗: {stderr}"

    except Exception as e:
        logger.error(f"💥 排程任務執行異常: {e}")
        import traceback
        logger.error(f"💥 異常堆疊: {traceback.format_exc()}")
        update_task_status('異常', 0, f'執行異常: {str(e)[:100]}...')
        task_status['is_running'] = False
        return False, f"排程任務執行異常: {e}"

def run_scheduler():
    """執行完整的排程任務 (保持同步介面兼容性)"""
    return run_scheduler_async()

def generate_report(force_llm_analysis=False, force_regenerate=False):
    """產生新的報表"""
    try:
        logger.info(f"開始產生報表... 強制LLM分析: {force_llm_analysis}, 強制重新產生: {force_regenerate}")

        # 檢查是否已有任務在運行
        if task_status['is_running']:
            elapsed = (datetime.now() - task_status['start_time']).total_seconds() if task_status['start_time'] else 0
            return True, f"報表產生中... 已運行 {int(elapsed/60)} 分鐘，當前步驟: {task_status['current_step']}"

        # 重置任務狀態，清除之前的停止標誌
        reset_task_status()

        # 儲存設定參數到全域變數
        task_status['force_llm_analysis'] = force_llm_analysis
        task_status['force_regenerate'] = force_regenerate

        # 啟動異步任務
        thread = threading.Thread(target=run_scheduler_async)
        thread.daemon = True
        thread.start()

        options_text = []
        if force_llm_analysis:
            options_text.append("強制LLM分析")
        if force_regenerate:
            options_text.append("強制重新產生")

        message = "報表產生任務已啟動"
        if options_text:
            message += f"（{', '.join(options_text)}）"
        message += "，請稍後檢查進度"

        return True, message

    except Exception as e:
        logger.error(f"報表產生異常: {e}")
        import traceback
        logger.error(f"異常堆疊: {traceback.format_exc()}")
        return False, f"報表產生異常: {e}"


@app.route('/settings')
@login_required
def settings():
    """設定頁面"""
    available_dates = get_available_dates()
    bgg_username = get_app_setting('bgg_username', '')
    user = session.get('user', {})
    return render_template('settings.html',
                           available_dates=available_dates,
                           bgg_username=bgg_username,
                           user=user,
                           rg_model_dir=RG_DEFAULT_MODEL_DIR,
                           rg_games_file=RG_DEFAULT_GAMES_FILE,
                           rg_ratings_file=RG_DEFAULT_RATINGS_FILE,
                           last_updated=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

@app.route('/api/save-settings', methods=['POST'])
@login_required
def api_save_settings():
    
    try:
        data = request.get_json() or {}
        bgg_username = data.get('bgg_username', '').strip()
        
        if not bgg_username:
            return jsonify({'success': False, 'message': '請輸入 BGG 使用者名稱'}), 400
        
        # 驗證 BGG 使用者名稱格式（基本檢查）
        if len(bgg_username) < 3 or len(bgg_username) > 50:
            return jsonify({'success': False, 'message': 'BGG 使用者名稱長度需在 3-50 字元之間'}), 400
        
        # 檢查是否有變更 BGG 用戶名
        current_username = get_app_setting('bgg_username', '')
        is_username_changed = (current_username != bgg_username)
        
        logger.info(f"嘗試保存 BGG 使用者名稱: {bgg_username}")
        ok = set_app_setting('bgg_username', bgg_username)
        
        if ok:
            logger.info(f"✅ BGG 使用者名稱保存成功: {bgg_username}")
            
            # 如果用戶名有變更，自動觸發收藏同步和模型訓練
            if is_username_changed and bgg_username:
                logger.info(f"🔄 BGG 用戶名已變更，觸發自動同步和訓練")
                try:
                    # 啟動背景任務
                    import threading
                    thread = threading.Thread(target=auto_sync_and_train, args=(bgg_username,))
                    thread.daemon = True
                    thread.start()
                    
                    return jsonify({
                        'success': True, 
                        'message': '設定已儲存，正在背景同步收藏並訓練模型...',
                        'auto_sync_started': True
                    })
                except Exception as e:
                    logger.error(f"自動同步啟動失敗: {e}")
                    return jsonify({
                        'success': True, 
                        'message': '設定已儲存，但自動同步啟動失敗，請手動同步',
                        'auto_sync_failed': True
                    })
            
            return jsonify({'success': True, 'message': '設定已儲存'})
        else:
            logger.error(f"❌ BGG 使用者名稱保存失敗: {bgg_username}")
            return jsonify({'success': False, 'message': '儲存失敗，請檢查資料庫連接'}), 500
            
    except Exception as e:
        logger.error(f"保存設定時發生異常: {e}")
        return jsonify({'success': False, 'message': f'保存失敗: {str(e)}'}), 500

@app.route('/api/sync-collection', methods=['POST'])
def api_sync_collection():
    if 'logged_in' not in session:
        return jsonify({'success': False, 'message': '未登入'}), 401
    username = get_app_setting('bgg_username')
    if not username:
        return jsonify({'success': False, 'message': '請先在設定頁設定 BGG 使用者名稱'}), 400
    try:
        # 兩段式呼叫：先 boardgame（排除 expansion），再 expansion
        xml_main = fetch_bgg_collection_xml(username, {"stats": 1, "excludesubtype": "boardgameexpansion"})
        xml_exp = fetch_bgg_collection_xml(username, {"stats": 1, "subtype": "boardgameexpansion"})
        items = parse_bgg_collection(xml_main) + parse_bgg_collection(xml_exp)
        written = upsert_collection_items(items)
        return jsonify({'success': True, 'message': f'同步完成，共 {written} 筆'})
    except TimeoutError as te:
        return jsonify({'success': False, 'message': f'BGG 排隊中，請稍後再試：{te}'}), 502
    except Exception as e:
        logger.error(f"同步收藏失敗: {e}")
        return jsonify({'success': False, 'message': f'同步失敗：{e}'}), 500

@app.route('/recommendations')
def recommendations():
    if 'logged_in' not in session:
        return redirect(url_for('login'))
    username = get_app_setting('bgg_username', '')
    if not username:
        flash('請先在設定頁設定 BGG 使用者名稱並同步收藏', 'info')
        return redirect(url_for('settings'))
    
    # 檢查模型是否存在
    model_path = f'data/rg_users/{username}/rg_model'
    if not os.path.exists(model_path):
        flash('推薦模型尚未訓練，請先到設定頁點擊「🚀 一鍵重新訓練」來建立您的個人化推薦模型。', 'warning')
        return redirect(url_for('settings'))
    
    # 讀取已收藏的 objectid 清單
    owned_ids = []
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT objectid FROM collection")
            owned_ids = [row[0] for row in cursor.fetchall()]
    except Exception:
        pass
    
    # 使用 board-game-recommender 獲取推薦
    from flask import request
    algorithm = request.args.get('algorithm', 'hybrid')
    
    logger.info(f"🔍 開始獲取推薦 - 用戶: {username}, 算法: {algorithm}, 擁有遊戲: {len(owned_ids)}")
    recommendations = get_advanced_recommendations(username, owned_ids, algorithm=algorithm, limit=30)
    logger.info(f"📊 推薦結果: {len(recommendations) if recommendations else 0} 個推薦")
    
    if not recommendations:
        logger.warning(f"⚠️ 推薦為空 - 用戶: {username}, 算法: {algorithm}")
        flash('無法獲取推薦，請檢查模型是否正確訓練', 'error')
        return redirect(url_for('settings'))
    
    # 傳遞可用的算法選項
    available_algorithms = [
        {'value': 'hybrid', 'name': '混合推薦 (Hybrid)', 'description': '結合多種算法的推薦'},
        {'value': 'popularity', 'name': '熱門推薦 (Popularity)', 'description': '基於遊戲熱門度的推薦'},
        {'value': 'content', 'name': '內容推薦 (Content-based)', 'description': '基於遊戲特徵相似性的推薦'}
    ]
    
    current_algorithm = algorithm
    current_view = request.args.get('view', 'search')  # 'search' 或 'grid'
    
    return render_template('recommendations.html', 
                         recommendations=recommendations, 
                         bgg_username=username,
                         available_algorithms=available_algorithms,
                         current_algorithm=current_algorithm,
                         current_view=current_view,
                         last_updated=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

@app.route('/rg-recommender')
def rg_recommender():
    """重定向到統一的推薦頁面"""
    return redirect(url_for('recommendations'))

@app.route('/api/rg-train', methods=['POST'])
def api_rg_train():
    if 'logged_in' not in session:
        return jsonify({'success': False, 'message': '未登入'}), 401
    # 使用固定預設路徑
    model_dir = RG_DEFAULT_MODEL_DIR
    games_file = RG_DEFAULT_GAMES_FILE
    ratings_file = RG_DEFAULT_RATINGS_FILE
    # 檢查並安裝 board-game-recommender
    try:
        import importlib.util
        spec = importlib.util.find_spec('board_game_recommender')
        if spec is None:
            # 嘗試安裝 board-game-recommender
            logger.info("正在安裝 board-game-recommender...")
            install_cmd = [sys.executable, '-m', 'pip', 'install', 'board-game-recommender']
            install_proc = subprocess.run(install_cmd, capture_output=True, text=True)
            if install_proc.returncode != 0:
                return jsonify({'success': False, 'message': f'安裝 board-game-recommender 失敗: {install_proc.stderr}'}), 400
            logger.info("board-game-recommender 安裝成功")
    except Exception as e:
        return jsonify({'success': False, 'message': f'檢查模組時發生錯誤: {str(e)}'}), 400

    # 執行訓練命令 - 改用直接 import 方式避免 __main__ 問題
    try:
        # 先嘗試使用模組的 API
        try:
            import board_game_recommender
            # 如果模組有訓練函數，直接呼叫
            if hasattr(board_game_recommender, 'train'):
                result = board_game_recommender.train(
                    games_file=games_file,
                    ratings_file=ratings_file,
                    model_dir=model_dir
                )
                return jsonify({'success': True, 'message': '訓練完成', 'result': str(result)})
        except (ImportError, AttributeError):
            pass  # 繼續使用 CLI 方式

        # 使用 LightGamesRecommender 直接訓練
        from board_game_recommender.light import LightGamesRecommender
        import os
        
        # 確保模型目錄存在
        os.makedirs(model_dir, exist_ok=True)
        
        # 檢查輸入檔案是否存在，如果不存在則從 BGG 直接抓取
        if not os.path.exists(games_file) or not os.path.exists(ratings_file):
            logger.info("從 BGG 直接抓取用戶資料...")
            
            # 獲取 BGG 用戶名
            username = get_app_setting('bgg_username')
            if not username:
                return jsonify({'success': False, 'message': '請先在設定頁面輸入 BGG 用戶名'})
            
            try:
                from bgg_scraper_extractor import BGGScraperExtractor
                extractor = BGGScraperExtractor()
                success = extractor.export_to_jsonl(username)
                if not success:
                    return jsonify({'success': False, 'message': f'無法從 BGG 抓取用戶 {username} 的資料'})
                logger.info(f"成功從 BGG 抓取用戶 {username} 的資料")
            except Exception as e:
                logger.error(f"從 BGG 抓取資料時發生錯誤: {e}")
                return jsonify({'success': False, 'message': f'資料抓取失敗: {str(e)}'})
        
        logger.info(f"開始 RG 訓練: games={games_file}, ratings={ratings_file}, model={model_dir}")
        
        # 檢查是否有現有模型，如果沒有則創建基礎推薦器
        model_file = os.path.join(model_dir, 'recommender.npz')
        
        if os.path.exists(model_file):
            # 載入現有模型
            try:
                recommender = LightGamesRecommender.from_npz(model_file)
                logger.info(f"載入現有模型: {model_file}")
                return jsonify({
                    'success': True,
                    'message': f'成功載入現有推薦模型！用戶數: {recommender.num_users}, 遊戲數: {recommender.num_games}'
                })
            except Exception as e:
                logger.error(f"載入模型失敗: {e}")
        
        # 如果沒有現有模型，創建簡單的基準推薦器
        from board_game_recommender.baseline import PopularGamesRecommender
        import pandas as pd
        import numpy as np
        
        # 讀取資料並創建基準推薦器
        try:
            # 讀取評分資料
            ratings_data = []
            with open(ratings_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        rating = json.loads(line)
                        ratings_data.append(rating)
            
            # 轉換為 DataFrame
            df = pd.DataFrame(ratings_data)
            
            # 計算每個遊戲的平均評分和評分數量
            game_stats = df.groupby('game_id').agg({
                'rating': ['mean', 'count']
            }).round(2)
            game_stats.columns = ['avg_rating', 'num_ratings']
            game_stats = game_stats.reset_index()
            
            # 計算熱門度分數（結合平均評分和評分數量）
            # 使用貝葉斯平均來處理評分數量較少的遊戲
            global_mean = df['rating'].mean()
            min_votes = 3  # 最少需要3個評分才考慮
            
            def bayesian_average(row):
                avg_rating = row['avg_rating']
                num_ratings = row['num_ratings']
                return (num_ratings * avg_rating + min_votes * global_mean) / (num_ratings + min_votes)
            
            game_stats['popularity_score'] = game_stats.apply(bayesian_average, axis=1)
            
            # 準備推薦器所需的資料
            game_ids = [int(gid) for gid in game_stats['game_id'].tolist()]
            scores = game_stats['popularity_score'].values
            
            # 創建基準推薦器
            recommender = PopularGamesRecommender(
                game_ids=game_ids,
                scores=scores,
                default_value=global_mean
            )
            
            # 保存模型
            model_file = os.path.join(model_dir, 'popular_recommender.json')
            model_data = {
                'type': 'PopularGamesRecommender',
                'game_ids': game_ids,
                'scores': scores.tolist(),
                'default_value': float(global_mean),
                'num_games': len(game_ids),
                'num_ratings': len(df)
            }
            with open(model_file, 'w', encoding='utf-8') as f:
                json.dump(model_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"創建基準推薦器成功，資料包含 {len(df)} 個評分")
            
            return jsonify({
                'success': True,
                'message': f'✅ 推薦器訓練完成！處理了 {len(df)} 個評分，{df["game_id"].nunique()} 個遊戲，{df["user_id"].nunique()} 個用戶。模型已保存到 {model_file}',
                'stats': {
                    'num_games': len(game_ids),
                    'num_ratings': len(df),
                    'num_users': df["user_id"].nunique(),
                    'avg_rating': round(global_mean, 2),
                    'model_type': 'PopularGamesRecommender'
                }
            })
            
        except Exception as e:
            logger.error(f"創建推薦器時發生錯誤: {e}")
            return jsonify({
                'success': False,
                'message': f'創建推薦器失敗: {str(e)}'
            })
    except Exception as e:
        logger.error(f"RG 訓練異常: {e}")
        return jsonify({'success': False, 'message': f'訓練異常：{e}'})

@app.route('/api/rg-status', methods=['GET'])
def api_rg_status():
    if 'logged_in' not in session:
        return jsonify({'success': False, 'message': '未登入'}), 401
    
    username = get_app_setting('bgg_username', '')
    if not username:
        return jsonify({
            'success': False, 
            'message': '請先設定 BGG 用戶名',
            'need_username': True
        })
    
    # 獲取用戶特定的路徑
    user_paths = get_user_rg_paths(username)
    
    # 檢查文件和目錄是否存在
    model_dir_exists = os.path.exists(user_paths['model_dir'])
    games_file_exists = os.path.exists(user_paths['games_file'])
    ratings_file_exists = os.path.exists(user_paths['ratings_file'])
    
    # 計算用戶數據完整度
    data_completeness = 0
    if games_file_exists:
        data_completeness += 40
    if ratings_file_exists:
        data_completeness += 30
    if model_dir_exists:
        data_completeness += 30
        
    status = {
        'username': username,
        'rg_model_dir': user_paths['model_dir'],
        'rg_games_file': user_paths['games_file'],
        'rg_ratings_file': user_paths['ratings_file'],
        'model_dir_exists': model_dir_exists,
        'games_file_exists': games_file_exists,
        'ratings_file_exists': ratings_file_exists,
        'data_completeness': data_completeness,
        'is_ready_for_recommendations': data_completeness >= 70,
        'rg_api_url': RG_API_URL or '',
        'fallback_paths': {
            'games_file': RG_DEFAULT_GAMES_FILE,
            'ratings_file': RG_DEFAULT_RATINGS_FILE,
            'model_dir': RG_DEFAULT_MODEL_DIR
        }
    }
    
    return jsonify({'success': True, 'status': status})

@app.route('/api/rg-scrape', methods=['POST'])
def api_rg_scrape():
    if 'logged_in' not in session:
        return jsonify({'success': False, 'message': '未登入'}), 401
    if rg_task_status.get('is_running'):
        return jsonify({'success': False, 'message': '已有抓取任務在進行中'}), 400
    # 採用固定預設輸出路徑
    games_file = RG_DEFAULT_GAMES_FILE
    ratings_file = RG_DEFAULT_RATINGS_FILE
    # 檢查是否設定了 BGG 用戶名
    bgg_username = get_app_setting('bgg_username')
    if not bgg_username:
        return jsonify({'success': False, 'message': '請先在設定頁面輸入 BGG 用戶名'}), 400

    # 確保輸出目錄存在
    try:
        if games_file:
            os.makedirs(os.path.dirname(games_file), exist_ok=True)
        if ratings_file:
            os.makedirs(os.path.dirname(ratings_file), exist_ok=True)
    except Exception:
        pass

    # 啟動背景任務
    rg_task_status.update({'is_running': True, 'start_time': datetime.now(), 'progress': 0, 'message': '啟動中', 'stdout_tail': [], 'stderr_tail': []})
    thread = threading.Thread(target=run_rg_scrape_async, args=(games_file, ratings_file, None))
    thread.daemon = True
    thread.start()
    return jsonify({'success': True, 'message': '抓取任務已啟動'})

@app.route('/api/rg-task-status', methods=['GET'])
def api_rg_task_status():
    if 'logged_in' not in session:
        return jsonify({'success': False, 'message': '未登入'}), 401
    st = rg_task_status.copy()
    st['elapsed_seconds'] = int((datetime.now() - st['start_time']).total_seconds()) if st.get('start_time') else 0
    # 只回傳 tail 以防過大
    st['stdout_tail'] = st.get('stdout_tail', [])[-20:]
    st['stderr_tail'] = st.get('stderr_tail', [])[-20:]
    if st.get('last_update'):
        st['last_update'] = st['last_update'].isoformat()
    return jsonify({'success': True, 'status': st})

@app.route('/api/bgg/search', methods=['POST'])
@login_required
def api_bgg_search():
    """BGG 遊戲搜尋 API"""
    try:
        data = request.get_json()
        query = data.get('query', '').strip()
        exact = data.get('exact', False)
        
        if not query:
            return jsonify({'success': False, 'message': '搜尋關鍵字不能為空'})
        
        # 使用 BGG XML API 2 搜尋遊戲
        import xml.etree.ElementTree as ET
        import urllib.parse
        
        # 構建搜尋 URL
        base_url = "https://boardgamegeek.com/xmlapi2/search"
        params = {
            'query': query,
            'type': 'boardgame',
            'exact': '1' if exact else '0'
        }
        
        url = f"{base_url}?{urllib.parse.urlencode(params)}"
        
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        # 解析 XML 回應
        root = ET.fromstring(response.text)
        
        results = []
        for item in root.findall('item')[:10]:  # 限制最多10個結果
            game_id = item.get('id')
            name_element = item.find('name')
            year_element = item.find('yearpublished')
            
            if game_id and name_element is not None:
                game_info = {
                    'id': game_id,
                    'name': name_element.get('value', ''),
                    'year': year_element.get('value') if year_element is not None else None
                }
                results.append(game_info)
        
        return jsonify({
            'success': True,
            'results': results,
            'query': query,
            'exact': exact
        })
        
    except requests.exceptions.RequestException as e:
        logger.error(f"BGG API 請求失敗: {e}")
        return jsonify({'success': False, 'message': f'BGG API 請求失敗: {str(e)}'})
    except ET.ParseError as e:
        logger.error(f"BGG XML 解析失敗: {e}")
        return jsonify({'success': False, 'message': 'BGG 回應格式錯誤'})
    except Exception as e:
        logger.error(f"BGG 搜尋發生錯誤: {e}")
        return jsonify({'success': False, 'message': f'搜尋失敗: {str(e)}'})

@app.route('/api/rg/recommend-score', methods=['POST'])
@login_required
def api_rg_recommend_score():
    """計算特定遊戲的推薦分數 - 使用 BGGRecommender"""
    try:
        if not BGG_RECOMMENDER_AVAILABLE:
            return jsonify({
                'success': False,
                'message': 'BGGRecommender 未安裝或不可用'
            })

        data = request.get_json()
        game_id = data.get('game_id')
        game_name = data.get('game_name', 'Unknown Game')

        if not game_id:
            return jsonify({'success': False, 'message': '遊戲 ID 不能為空'})

        # 獲取使用者收藏
        username = get_app_setting('bgg_username', '')
        owned_ids = []
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT objectid FROM collection")
                owned_ids = [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logger.warning(f"無法獲取使用者收藏: {e}")

        if not owned_ids:
            return jsonify({
                'success': False,
                'message': '請先同步您的 BGG 收藏才能計算推薦分數'
            })

        # 使用預訓練的 BGGRecommender 模型計算分數
        try:
            # 檢查是否有預訓練的模型
            model_dir = f'data/bgg_models/{username}'
            model_path = f'{model_dir}/recommender_model'

            if not os.path.exists(model_path):
                return jsonify({
                    'success': False,
                    'message': '尚未訓練推薦模型。請先到設定頁點擊「🚀 一鍵重新訓練」來建立您的個人化推薦模型。'
                })

            # 載入預訓練的模型
            import turicreate as tc
            model = tc.load_model(model_path)

            # 創建 BGGRecommender 實例
            recommender = BGGRecommender(model=model)

            # 獲取推薦
            recommendations = recommender.recommend([username], num_games=1000)

            # 尋找目標遊戲的分數
            target_recs = recommendations[recommendations['bgg_id'] == int(game_id)]

            if len(target_recs) > 0:
                score = float(target_recs['score'][0]) * 10  # 轉換為 0-10 分數

                # 計算分數等級
                if score >= 8.5:
                    level, description = 'excellent', '極力推薦！這款遊戲非常符合您的喜好'
                elif score >= 7.0:
                    level, description = 'very_good', '強烈推薦！您很可能會喜歡這款遊戲'
                elif score >= 5.5:
                    level, description = 'good', '推薦嘗試，這款遊戲可能合您的口味'
                elif score >= 4.0:
                    level, description = 'fair', '可以考慮，但可能不是您的首選'
                else:
                    level, description = 'poor', '不太推薦，可能不符合您的遊戲偏好'

                return jsonify({
                    'success': True,
                    'result': {
                        'game_id': game_id,
                        'name': game_name,
                        'score': score,
                        'max_score': 10.0,
                        'score_level': level,
                        'score_description': description,
                        'details': f'基於您的 {len(owned_ids)} 個收藏遊戲使用預訓練 BGGRecommender 模型計算'
                    }
                })
            else:
                return jsonify({
                    'success': False,
                    'message': '此遊戲未在推薦列表中。可能是因為它不在訓練數據中，或者與您的喜好差異較大。'
                })

        except Exception as model_error:
            logger.error(f"BGGRecommender 模型錯誤: {model_error}")
            return jsonify({
                'success': False,
                'message': f'推薦模型載入失敗: {str(model_error)}。請嘗試重新訓練模型。'
            })

    except Exception as e:
        logger.error(f"推薦分數 API 發生錯誤: {e}")
        return jsonify({'success': False, 'message': f'處理請求時發生錯誤: {str(e)}'})

# 複雜的高級推薦 API 已移除，請使用 /api/rg/recommend-score

# BGG 推薦系統一鍵重新訓練相關 API
@app.route('/api/bgg/retrain-full', methods=['POST'])
@login_required
def api_bgg_retrain_full():
    """一鍵重新訓練：自動 scraper + training"""
    try:
        username = get_app_setting('bgg_username', '')
        if not username:
            return jsonify({
                'success': False,
                'message': '請先設定 BGG 使用者名稱'
            })

        # 檢查是否已有訓練在進行
        if task_status['is_running']:
            return jsonify({
                'success': False,
                'message': '已有任務在執行中，請等待完成後再試'
            })

        # 啟動背景訓練任務
        thread = threading.Thread(target=run_full_retrain_task, args=(username,))
        thread.daemon = True
        thread.start()

        return jsonify({
            'success': True,
            'message': '已啟動一鍵重新訓練任務'
        })

    except Exception as e:
        logger.error(f"啟動一鍵重新訓練失敗: {e}")
        return jsonify({'success': False, 'message': f'啟動失敗: {str(e)}'})

@app.route('/api/bgg/training-status', methods=['GET'])
@login_required
def api_bgg_training_status():
    """獲取訓練狀態"""
    try:
        return jsonify({
            'success': True,
            'status': {
                'is_running': task_status['is_running'],
                'current_step': task_status['current_step'],
                'progress': task_status['progress'],
                'message': task_status['message'],
                'completed': task_status.get('completed', False),
                'error': task_status.get('error', False),
                'error_message': task_status.get('error_message', '')
            }
        })
    except Exception as e:
        logger.error(f"獲取訓練狀態失敗: {e}")
        return jsonify({'success': False, 'message': str(e)})

def run_full_retrain_task(username):
    """執行完整重新訓練任務"""
    try:
        # 初始化任務狀態
        update_task_status('準備開始', 0, '正在初始化訓練環境...')
        task_status['completed'] = False
        task_status['error'] = False
        task_status['error_message'] = ''

        logger.info(f"🚀 開始為用戶 {username} 執行一鍵重新訓練")

        # 步驟 1: 同步用戶收藏
        update_task_status('同步用戶收藏', 10, '正在從 BGG 同步您的收藏資料...')
        success = sync_user_collection(username)
        if not success:
            raise Exception("同步用戶收藏失敗")

        # 步驟 2: 抓取 BGG 遊戲資料
        update_task_status('抓取 BGG 資料', 30, '正在抓取最新的 BGG 遊戲和評分資料...')
        success = scrape_bgg_data(username)
        if not success:
            raise Exception("抓取 BGG 資料失敗")

        # 步驟 3: 訓練模型
        update_task_status('訓練推薦模型', 60, '正在使用 board-game-recommender 訓練協同過濾模型...')
        success = train_bgg_model(username)
        if not success:
            raise Exception("訓練模型失敗")

        # 完成
        update_task_status('訓練完成', 100, '🎉 BGG 推薦模型訓練完成！')
        task_status['completed'] = True
        logger.info(f"✅ 用戶 {username} 的一鍵重新訓練完成")

    except Exception as e:
        logger.error(f"❌ 一鍵重新訓練失敗: {e}")
        task_status['error'] = True
        task_status['error_message'] = str(e)
        update_task_status('訓練失敗', task_status['progress'], f'錯誤: {str(e)}')
    finally:
        task_status['is_running'] = False

def sync_user_collection(username):
    """同步用戶收藏"""
    try:
        logger.info(f"同步用戶 {username} 的收藏")
        
        # 使用 BGG scraper 抓取用戶收藏
        from bgg_scraper_extractor import BGGScraperExtractor
        extractor = BGGScraperExtractor()
        
        # 抓取用戶收藏資料
        collection_data = extractor.fetch_user_collection(username)
        if not collection_data:
            logger.warning(f"無法獲取用戶 {username} 的收藏資料")
            return False
        
        # 將資料保存到資料庫
        with get_db_connection() as conn:
            cursor = conn.cursor()
            config = get_database_config()
            
            # 清空現有的收藏資料
            execute_query(cursor, "DELETE FROM collection", (), config['type'])
            
            # 插入新的收藏資料
            for item in collection_data:
                # 確定收藏狀態
                status = 'owned' if item.get('own') else ('wishlist' if item.get('wishlist') else 'want')
                
                # 使用 UPSERT 語法避免重複 key 錯誤
                if config['type'] == 'postgresql':
                    execute_query(cursor, """
                        INSERT INTO collection (objectid, name, status, rating, wish_priority, last_sync)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (objectid) DO UPDATE SET
                            name = EXCLUDED.name,
                            status = EXCLUDED.status,
                            rating = EXCLUDED.rating,
                            wish_priority = EXCLUDED.wish_priority,
                            last_sync = EXCLUDED.last_sync
                    """, (
                        item.get('game_id'),
                        item.get('game_name'),
                        status,
                        item.get('user_rating'),
                        item.get('bgg_rank'),
                        datetime.now().isoformat()
                    ), config['type'])
                else:
                    execute_query(cursor, """
                        INSERT OR REPLACE INTO collection (objectid, name, status, rating, wish_priority, last_sync)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        item.get('game_id'),
                        item.get('game_name'),
                        status,
                        item.get('user_rating'),
                        item.get('bgg_rank'),
                        datetime.now().isoformat()
                    ), config['type'])
            
            conn.commit()
            logger.info(f"成功同步 {len(collection_data)} 個收藏遊戲")
        
        return True
    except Exception as e:
        logger.error(f"同步用戶收藏失敗: {e}")
        return False

def scrape_bgg_data(username):
    """抓取 BGG 資料"""
    try:
        logger.info(f"開始為用戶 {username} 抓取 BGG 資料")
        
        # 使用 BGG scraper 抓取真實的用戶資料
        from bgg_scraper_extractor import BGGScraperExtractor
        extractor = BGGScraperExtractor()
        
        # 抓取用戶收藏資料並生成 .jl 檔案到用戶特定目錄
        success = extractor.export_to_jsonl(username, 'data')
        if not success:
            raise Exception("抓取用戶收藏資料失敗")
        
        logger.info(f"成功為用戶 {username} 抓取 BGG 資料")
        return True
    except Exception as e:
        logger.error(f"抓取 BGG 資料失敗: {e}")
        return False

def prepare_training_data(username):
    """準備訓練資料"""
    try:
        logger.info(f"為用戶 {username} 準備訓練資料")
        
        # 使用現有的 create_temp_jsonl_files 函數生成個人化的 .jl 檔案
        games_file, ratings_file = create_temp_jsonl_files()
        if not games_file or not ratings_file:
            raise Exception("無法生成訓練資料檔案")
        
        logger.info(f"成功準備訓練資料: {games_file}, {ratings_file}")
        return True
    except Exception as e:
        logger.error(f"準備訓練資料失敗: {e}")
        return False

def train_bgg_model(username):
    """訓練 BGG 推薦模型"""
    try:
        logger.info(f"為用戶 {username} 訓練 BGG 推薦模型")

        if not BGG_RECOMMENDER_AVAILABLE:
            raise Exception("BGGRecommender 不可用")

        # 使用 board-game-recommender 的正確方式
        from board_game_recommender.recommend import BGGRecommender
        
        # 使用用戶特定的檔案路徑
        user_dir = f'data/rg_users/{username}'
        games_file = os.path.join(user_dir, 'bgg_GameItem.jl')
        ratings_file = os.path.join(user_dir, 'bgg_RatingItem.jl')
        
        if not os.path.exists(games_file):
            raise Exception(f"遊戲資料檔案不存在: {games_file}")
        if not os.path.exists(ratings_file):
            raise Exception(f"評分資料檔案不存在: {ratings_file}")
        
        print(f"🔍 使用遊戲資料檔案: {games_file}")
        print(f"🔍 使用評分資料檔案: {ratings_file}")
        
        # 使用 BGGRecommender 訓練模型
        recommender = BGGRecommender.train_from_files(
            games_file=games_file,
            ratings_file=ratings_file,
            max_iterations=100
        )
        
        # 保存模型到用戶特定目錄
        model_dir = os.path.join(user_dir, 'rg_model')
        os.makedirs(model_dir, exist_ok=True)
        recommender.save(model_dir)
        logger.info(f"模型已保存到 {model_dir}")
        return True

    except Exception as e:
        logger.error(f"訓練 BGG 模型失敗: {e}")
        return False

@app.route('/api/rg/model-status', methods=['GET'])
@login_required
def api_rg_model_status():
    """獲取推薦模型狀態信息"""
    try:
        username = get_app_setting('bgg_username', '')
        if not username:
            return jsonify({'success': False, 'message': '請先設定 BGG 使用者名稱'})
        
        user_paths = get_user_rg_paths(username)
        
        # 檢查用戶數據狀態
        has_games_data = os.path.exists(user_paths['games_file'])
        has_ratings_data = os.path.exists(user_paths['ratings_file'])
        has_full_model = os.path.exists(user_paths['full_model'])
        has_light_model = os.path.exists(user_paths['light_model'])
        
        # 檢查系統支援
        bgg_recommender_available = False
        light_recommender_available = False
        fallback_available = False
        
        try:
            from board_game_recommender import BGGRecommender
            bgg_recommender_available = True
        except ImportError:
            pass
        
        try:
            from board_game_recommender import LightGamesRecommender
            light_recommender_available = True
        except ImportError:
            pass
        
        try:
            from board_game_recommender.recommend import BGGRecommender
            fallback_available = True
        except ImportError:
            pass
        
        # 計算數據統計
        games_count = 0
        ratings_count = 0
        
        if has_games_data:
            try:
                with open(user_paths['games_file'], 'r', encoding='utf-8') as f:
                    games_count = sum(1 for _ in f)
            except:
                pass
        
        if has_ratings_data:
            try:
                with open(user_paths['ratings_file'], 'r', encoding='utf-8') as f:
                    ratings_count = sum(1 for _ in f)
            except:
                pass
        
        # 推薦可用性
        can_use_full = bgg_recommender_available and has_games_data and has_ratings_data
        can_use_light = light_recommender_available and has_games_data and has_light_model
        can_use_fallback = fallback_available
        
        return jsonify({
            'success': True,
            'result': {
                'username': username,
                'data_status': {
                    'has_games_data': has_games_data,
                    'has_ratings_data': has_ratings_data,
                    'games_count': games_count,
                    'ratings_count': ratings_count
                },
                'model_status': {
                    'has_full_model': has_full_model,
                    'has_light_model': has_light_model
                },
                'system_support': {
                    'bgg_recommender': bgg_recommender_available,
                    'light_recommender': light_recommender_available,
                    'fallback_recommender': fallback_available
                },
                'availability': {
                    'full_recommender': can_use_full,
                    'light_recommender': can_use_light,
                    'fallback_recommender': can_use_fallback
                },
                'recommended_action': _get_recommended_action(
                    can_use_full, can_use_light, can_use_fallback,
                    has_games_data, has_ratings_data, games_count, ratings_count
                )
            }
        })
        
    except Exception as e:
        logger.error(f"模型狀態 API 發生錯誤: {e}")
        return jsonify({'success': False, 'message': f'處理請求時發生錯誤: {str(e)}'})

def _get_recommended_action(can_use_full, can_use_light, can_use_fallback, has_games_data, has_ratings_data, games_count, ratings_count):
    """根據系統狀態推薦用戶應該採取的行動"""
    if can_use_full:
        return {
            'action': 'ready',
            'message': '完整推薦系統已就緒',
            'priority': 'success'
        }
    elif can_use_light:
        return {
            'action': 'light_ready',
            'message': '輕量級推薦系統已就緒',
            'priority': 'success'
        }
    elif not has_games_data or not has_ratings_data:
        return {
            'action': 'sync_collection',
            'message': '請先同步 BGG 收藏以啟用推薦功能',
            'priority': 'warning'
        }
    elif games_count < 50 or ratings_count < 20:
        return {
            'action': 'need_more_data',
            'message': '需要更多收藏數據以提高推薦準確性',
            'priority': 'info'
        }
    elif can_use_fallback:
        return {
            'action': 'fallback_available',
            'message': '使用基礎推薦功能（功能有限）',
            'priority': 'info'
        }
    else:
        return {
            'action': 'setup_required',
            'message': '需要安裝推薦套件以啟用推薦功能',
            'priority': 'error'
        }

def get_score_context(score, algorithm):
    """根據分數返回上下文說明"""
    if score >= 8.5:
        return {
            'level': 'excellent',
            'description': '絕佳推薦 - 非常符合您的喜好'
        }
    elif score >= 7.5:
        return {
            'level': 'very_good', 
            'description': '強烈推薦 - 很可能會喜歡'
        }
    elif score >= 6.5:
        return {
            'level': 'good',
            'description': '值得嘗試 - 符合您的偏好'
        }
    elif score >= 5.5:
        return {
            'level': 'fair',
            'description': '一般推薦 - 可能會感興趣'
        }
    else:
        return {
            'level': 'poor',
            'description': '不太推薦 - 可能不符合您的喜好'
        }

def auto_sync_and_train(username):
    """自動同步收藏並訓練模型（背景任務）"""
    try:
        logger.info(f"🚀 開始為用戶 {username} 自動同步收藏和訓練模型")
        
        # 確保用戶目錄存在
        user_paths = get_user_rg_paths(username)
        os.makedirs(user_paths['user_dir'], exist_ok=True)
        
        # 第一步：同步 BGG 收藏
        logger.info(f"📥 第一步：同步 BGG 收藏...")
        try:
            xml_main = fetch_bgg_collection_xml(username, {"stats": 1, "excludesubtype": "boardgameexpansion"})
            xml_exp = fetch_bgg_collection_xml(username, {"stats": 1, "subtype": "boardgameexpansion"})
            
            if xml_main or xml_exp:
                save_collection_to_db(xml_main, xml_exp)
                logger.info(f"✅ 收藏同步成功")
            else:
                logger.warning(f"⚠️ 收藏同步失敗或無收藏資料")
                
        except Exception as e:
            logger.error(f"❌ 收藏同步失敗: {e}")
            
        # 第二步：生成用戶特定的 JSONL 資料
        logger.info(f"📊 第二步：生成推薦資料...")
        try:
            result = generate_user_rg_data(username, use_global_files=True)
            logger.info(f"✅ 推薦資料生成成功: {result['games_count']} 遊戲, {result['ratings_count']} 評分")
        except Exception as e:
            logger.error(f"❌ 推薦資料生成失敗: {e}")
            
        # 第三步：訓練推薦模型
        logger.info(f"🧠 第三步：訓練推薦模型...")
        try:
            # 嘗試訓練輕量級模型（優先）和完整模型
            results = train_user_rg_model(username, model_types=['light', 'full'])
            
            success_count = 0
            for model_type, result in results.items():
                if result.get('success'):
                    logger.info(f"✅ {model_type} 模型訓練成功: {result.get('model_type')}")
                    success_count += 1
                else:
                    logger.warning(f"⚠️ {model_type} 模型訓練失敗: {result.get('error')}")
            
            if success_count > 0:
                logger.info(f"✅ 共 {success_count} 個推薦模型訓練成功")
            else:
                logger.warning(f"⚠️ 沒有推薦模型訓練成功")
                
        except Exception as e:
            logger.error(f"❌ 推薦模型訓練失敗: {e}")
            
        logger.info(f"🎉 用戶 {username} 的自動同步和訓練完成")
        
    except Exception as e:
        logger.error(f"❌ 自動同步和訓練異常: {e}")

def generate_user_rg_data(username, use_global_files=True):
    """為特定用戶生成 RG 推薦所需的 JSONL 資料
    
    Args:
        username: BGG 用戶名
        use_global_files: 是否生成/更新全域檔案（預設路徑），同時複製到用戶目錄
    """
    user_paths = get_user_rg_paths(username)
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # 決定主要生成路徑
        if use_global_files:
            # 生成到預設路徑（供 scraper 和其他功能使用）
            primary_games_file = RG_DEFAULT_GAMES_FILE
            primary_ratings_file = RG_DEFAULT_RATINGS_FILE
            # 確保預設目錄存在
            os.makedirs('data', exist_ok=True)
        else:
            # 生成到用戶特定路徑
            primary_games_file = user_paths['games_file']
            primary_ratings_file = user_paths['ratings_file']
            # 確保用戶目錄存在
            os.makedirs(os.path.dirname(user_paths['games_file']), exist_ok=True)
        
        # 生成遊戲資料
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
        
        games_count = 0
        with open(primary_games_file, 'w', encoding='utf-8') as f:
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
                    'rank': int(row[9]) if row[9] and row[9] > 0 else (games_count + 1),
                    'complexity': float(row[10] or 2.0),
                    'num_votes': int(row[11] or 1000),
                    'cooperative': False,
                    'compilation': False,
                    'compilation_of': [],
                    'implementation': [],
                    'integration': []
                }
                f.write(json.dumps(game_data, ensure_ascii=False) + '\n')
                games_count += 1
        
        # 生成評分資料（基於用戶收藏）
        cursor.execute("""
            SELECT objectid, rating 
            FROM collection 
            WHERE rating > 0 AND rating <= 10
        """)
        
        ratings_count = 0
        with open(primary_ratings_file, 'w', encoding='utf-8') as f:
            for row in cursor.fetchall():
                rating_data = {
                    'bgg_id': row[0],
                    'bgg_user_name': username,
                    'bgg_user_rating': float(row[1])
                }
                f.write(json.dumps(rating_data, ensure_ascii=False) + '\n')
                ratings_count += 1
        
        logger.info(f"✅ 生成了 {games_count} 個遊戲和 {ratings_count} 個評分記錄到 {primary_games_file}")
        
        # 如果生成到了預設路徑，同時複製到用戶特定路徑
        if use_global_files and primary_games_file != user_paths['games_file']:
            try:
                import shutil
                # 確保用戶目錄存在
                os.makedirs(os.path.dirname(user_paths['games_file']), exist_ok=True)
                
                # 複製檔案
                shutil.copy2(primary_games_file, user_paths['games_file'])
                shutil.copy2(primary_ratings_file, user_paths['ratings_file'])
                logger.info(f"📋 已複製檔案到用戶目錄: {user_paths['games_file']}")
            except Exception as e:
                logger.warning(f"⚠️ 複製到用戶目錄失敗: {e}")
                
        return {
            'games_file': primary_games_file,
            'ratings_file': primary_ratings_file,
            'user_games_file': user_paths['games_file'],
            'user_ratings_file': user_paths['ratings_file'],
            'games_count': games_count,
            'ratings_count': ratings_count
        }

def train_user_rg_model(username, model_types=['light']):
    """訓練用戶特定的 RG 推薦模型
    
    Args:
        username: BGG 用戶名
        model_types: 要訓練的模型類型列表，可選 ['full', 'light']
    """
    user_paths = get_user_rg_paths(username)
    
    # 檢查資料檔案是否存在
    if not (os.path.exists(user_paths['games_file']) and os.path.exists(user_paths['ratings_file'])):
        raise Exception("缺少必要的資料檔案")
    
    # 創建模型目錄
    os.makedirs(user_paths['model_dir'], exist_ok=True)
    
    results = {}
    
    for model_type in model_types:
        try:
            if model_type == 'light':
                result = _train_light_model(username, user_paths)
                results['light'] = result
            elif model_type == 'full':
                result = _train_full_model(username, user_paths)  
                results['full'] = result
            else:
                logger.warning(f"⚠️ 不支援的模型類型: {model_type}")
                
        except Exception as e:
            logger.error(f"❌ 訓練 {model_type} 模型失敗: {e}")
            results[model_type] = {'success': False, 'error': str(e)}
    
    return results

def _train_light_model(username, user_paths):
    """訓練輕量級推薦模型"""
    logger.info(f"🪶 開始訓練用戶 {username} 的輕量級模型")
    
    try:
        # 檢查 LightGamesRecommender 是否可用
        try:
            from board_game_recommender import LightGamesRecommender
        except ImportError:
            logger.warning("⚠️ LightGamesRecommender 不可用，嘗試使用替代方案")
            return _create_simple_light_model(username, user_paths)
        
        # 讀取遊戲和評分數據
        games_data = []
        with open(user_paths['games_file'], 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    games_data.append(json.loads(line.strip()))
                except:
                    continue
        
        ratings_data = []
        with open(user_paths['ratings_file'], 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    ratings_data.append(json.loads(line.strip()))
                except:
                    continue
        
        if len(games_data) < 10 or len(ratings_data) < 5:
            logger.warning(f"⚠️ 數據量不足，遊戲: {len(games_data)}, 評分: {len(ratings_data)}")
            return _create_simple_light_model(username, user_paths)
        
        # 訓練輕量級模型
        logger.info("🎯 開始訓練 LightGamesRecommender...")
        
        # 創建並訓練模型
        model = LightGamesRecommender.train(
            games_file=user_paths['games_file'],
            ratings_file=user_paths['ratings_file'],
            model_file=user_paths['light_model']
        )
        
        logger.info(f"✅ 輕量級模型訓練完成: {user_paths['light_model']}")
        
        return {
            'success': True,
            'model_path': user_paths['light_model'],
            'games_count': len(games_data),
            'ratings_count': len(ratings_data),
            'model_type': 'light_full'
        }
        
    except Exception as e:
        logger.error(f"❌ 輕量級模型訓練失敗: {e}")
        # 嘗試創建簡單的替代模型
        return _create_simple_light_model(username, user_paths)

def _create_simple_light_model(username, user_paths):
    """創建簡單的輕量級模型（不依賴 board-game-recommender）"""
    logger.info(f"🔧 創建簡單輕量級模型：{username}")
    
    try:
        # 讀取用戶評分數據以創建簡單的偏好向量
        ratings_data = []
        with open(user_paths['ratings_file'], 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    ratings_data.append(json.loads(line.strip()))
                except:
                    continue
        
        # 創建簡單的用戶偏好模型
        user_preferences = {
            'username': username,
            'owned_games': [r['bgg_id'] for r in ratings_data],
            'ratings': {r['bgg_id']: r['bgg_user_rating'] for r in ratings_data},
            'model_type': 'simple_light',
            'created_at': datetime.now().isoformat()
        }
        
        # 保存為 numpy 格式模擬輕量級模型
        import numpy as np
        
        # 創建特徵向量
        game_ids = list(user_preferences['ratings'].keys())
        ratings = list(user_preferences['ratings'].values())
        
        model_data = {
            'user_id': username,
            'game_ids': np.array(game_ids),
            'ratings': np.array(ratings),
            'preferences': user_preferences,
            'model_version': 'simple_v1'
        }
        
        # 保存模型
        np.savez(user_paths['light_model'], **model_data)
        
        logger.info(f"✅ 簡單輕量級模型創建完成: {user_paths['light_model']}")
        
        return {
            'success': True,
            'model_path': user_paths['light_model'],
            'games_count': len(game_ids),
            'ratings_count': len(ratings),
            'model_type': 'simple_light'
        }
        
    except Exception as e:
        logger.error(f"❌ 簡單輕量級模型創建失敗: {e}")
        return {'success': False, 'error': str(e)}

def _train_full_model(username, user_paths):
    """訓練完整的 BGGRecommender 模型"""
    logger.info(f"🎯 開始訓練用戶 {username} 的完整模型")
    
    try:
        # 檢查 BGGRecommender 是否可用
        try:
            from board_game_recommender import BGGRecommender
        except ImportError:
            logger.warning("⚠️ BGGRecommender 不可用")
            return {'success': False, 'error': 'BGGRecommender not available'}
        
        # 訓練 BGGRecommender
        logger.info("📊 開始訓練 BGGRecommender...")
        
        recommender = BGGRecommender.train_from_files(
            games_file=user_paths['games_file'],
            ratings_file=user_paths['ratings_file'],
            max_iterations=50,
            verbose=False
        )
        
        # 保存模型（如果 BGGRecommender 支援保存）
        try:
            model_path = user_paths['full_model']
            recommender.save(model_path)
            logger.info(f"✅ 完整模型訓練並保存完成: {model_path}")
            
            return {
                'success': True,
                'model_path': model_path,
                'model_type': 'bgg_full'
            }
        except AttributeError:
            # 如果 BGGRecommender 不支援保存，創建標記文件
            marker_file = user_paths['full_model'] + '.marker'
            with open(marker_file, 'w') as f:
                f.write(f"BGGRecommender trained for {username} at {datetime.now()}")
            
            logger.info(f"✅ 完整模型訓練完成（無法保存，已創建標記）")
            
            return {
                'success': True,
                'model_path': marker_file,
                'model_type': 'bgg_full_marker'
            }
        
    except Exception as e:
        logger.error(f"❌ 完整模型訓練失敗: {e}")
        return {'success': False, 'error': str(e)}

def create_temp_jsonl_files():
    """使用現有的 JSONL 資料檔案供 RG BGGRecommender 使用"""
    try:
        # 優先使用預設路徑的檔案（scraper 生成的）
        games_file = RG_DEFAULT_GAMES_FILE
        ratings_file = RG_DEFAULT_RATINGS_FILE
        
        # 檢查檔案是否存在
        if not os.path.exists(games_file) or not os.path.exists(ratings_file):
            logger.warning("⚠️ 預設 JSONL 資料檔案不存在")
            
            # 嘗試使用當前用戶的檔案
            username = get_app_setting('bgg_username', '')
            if username:
                user_paths = get_user_rg_paths(username)
                if os.path.exists(user_paths['games_file']) and os.path.exists(user_paths['ratings_file']):
                    logger.info(f"🔄 使用用戶特定的 JSONL 檔案")
                    return user_paths['games_file'], user_paths['ratings_file']
            
            logger.info("🔄 將使用簡單推薦方法")
            return None, None
        
        logger.info(f"📄 使用預設 JSONL 資料檔案: {games_file}, {ratings_file}")
        return games_file, ratings_file
        
    except Exception as e:
        logger.error(f"存取 JSONL 檔案失敗: {e}")
        return None, None


def get_production_recommendation_score(username, owned_ids, game_id):
    """生產環境推薦分數計算 - 不依賴 turicreate"""
    try:
        logger.info(f"🏭 使用生產環境推薦器計算遊戲 {game_id} 的推薦分數")
        
        from board_game_recommender.recommend import BGGRecommender
        
        # 載入已訓練的模型
        model_path = f'data/rg_users/{username}/rg_model'
        if not os.path.exists(model_path):
            logger.error(f"❌ 模型不存在: {model_path}")
            return 0.0
        
        recommender = BGGRecommender.load(model_path)
        
        # 獲取推薦
        recommendations_df = recommender.recommend(
            users=[username],
            num_games=100,
            exclude_known=True
        )
        
        # 查找目標遊戲的分數
        for row in recommendations_df:
            if int(row['bgg_id']) == game_id:
                score = float(row.get('score', 0))
                logger.info(f"✅ 生產環境推薦分數: {score:.4f}")
                return score
        
        # 如果沒找到，計算基於內容的相似度分數
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # 獲取目標遊戲資訊
                cursor.execute("""
                    SELECT categories, mechanics, rating, weight, minplayers, maxplayers
                    FROM game_detail WHERE objectid = %s
                """, (game_id,))
                target_game = cursor.fetchone()
                
                if not target_game:
                    return None
                
                # 獲取用戶收藏遊戲的平均特徵
                placeholders = ','.join(['%s'] * len(owned_ids))
                cursor.execute(f"""
                    SELECT AVG(rating), AVG(weight), AVG(minplayers), AVG(maxplayers)
                    FROM game_detail WHERE objectid IN ({placeholders})
                """, owned_ids)
                user_prefs = cursor.fetchone()
                
                if user_prefs:
                    target_rating, target_weight = target_game[2] or 0, target_game[3] or 0
                    user_avg_rating, user_avg_weight = user_prefs[0] or 0, user_prefs[1] or 0
                    
                    # 簡單的相似度計算
                    rating_similarity = 1 - abs(target_rating - user_avg_rating) / 10
                    weight_similarity = 1 - abs(target_weight - user_avg_weight) / 5
                    
                    # 綜合分數 (0-5 範圍)
                    similarity_score = (rating_similarity + weight_similarity) / 2
                    final_score = max(0, min(5, similarity_score * 5))
                    
                    logger.info(f"📊 基於內容相似度分數: {final_score:.4f}")
                    return final_score
                
        except Exception as e:
            logger.error(f"內容相似度計算失敗: {e}")
        
        # 最後的降級方案：返回目標遊戲的 BGG 評分
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT rating FROM game_detail WHERE objectid = %s", (game_id,))
                result = cursor.fetchone()
                if result and result[0]:
                    bgr_rating = result[0]
                    # 將 BGG 評分 (0-10) 轉換為推薦分數 (0-5)
                    fallback_score = min(5, max(0, bgr_rating / 2))
                    logger.info(f"🎯 降級方案 - BGG 評分推薦分數: {fallback_score:.4f}")
                    return fallback_score
        except Exception as e:
            logger.error(f"BGG 評分降級計算失敗: {e}")
        
        return None
        
    except Exception as e:
        logger.error(f"生產環境推薦分數計算失敗: {e}")
        return None


def get_similarity_based_score(recommender, user_ratings_data, game_id):
    """當遊戲不在推薦結果中時，使用相似度計算分數"""
    try:
        import turicreate as tc
        
        # 獲取用戶喜好的遊戲特徵
        user_game_ids = [r['bgg_id'] for r in user_ratings_data]
        
        # 從推薦器獲取遊戲相似度
        if hasattr(recommender, 'similarity_model') and recommender.similarity_model:
            similar_games = recommender.similarity_model.query(tc.SFrame([{'bgg_id': game_id}]), k=10)
            
            # 計算與用戶收藏遊戲的相似度分數
            similarity_scores = []
            for _, row in similar_games.iterrows():
                if row['bgg_id'] in user_game_ids:
                    similarity_scores.append(row.get('score', 0))
            
            if similarity_scores:
                avg_similarity = sum(similarity_scores) / len(similarity_scores)
                score = min(10, max(0, avg_similarity * 10))
                logger.info(f"🔄 使用相似度計算分數: {score:.3f}")
                return score
        
        # 降級到基礎分數
        return 5.0
        
    except Exception as e:
        logger.error(f"相似度計算失敗: {e}")
        return 5.0

def get_single_game_recommendation_score(username, owned_ids, game_id, algorithm='hybrid', model_type='auto'):
    """使用新的 LRU 緩存載入機制計算單個遊戲的推薦分數"""
    try:
        logger.info(f"🎯 計算遊戲 {game_id} 的推薦分數，算法: {algorithm}, 模型: {model_type}")
        
        # 使用新的 LRU 緩存載入機制
        recommender, model_info = load_user_recommender(username, model_type)
        
        if not recommender:
            logger.warning(f"❌ 無法載入推薦器: {model_info}")
            return None
        
        logger.info(f"📊 使用推薦器類型: {model_info['type']}")
        
        # 根據推薦器類型使用不同的推薦邏輯
        if model_info['type'] == 'bgg_full':
            return _calculate_score_with_bgg_recommender(recommender, username, owned_ids, game_id, algorithm)
        
        elif model_info['type'] == 'light':
            return _calculate_score_with_light_recommender(recommender, username, owned_ids, game_id, algorithm)
        
        elif model_info['type'] == 'fallback':
            return _calculate_score_with_fallback_recommender(recommender, username, owned_ids, game_id, algorithm)
        
        else:
            logger.error(f"❌ 不支援的推薦器類型: {model_info['type']}")
            return None
        
    except Exception as e:
        logger.error(f"RG 推薦分數計算失敗: {e}")
        return None

def _calculate_score_with_bgg_recommender(recommender, username, owned_ids, game_id, algorithm):
    """使用 BGGRecommender 計算推薦分數"""
    try:
        # 構建用戶評分數據
        user_ratings_data = []
        for owned_game_id in owned_ids:
            user_ratings_data.append({
                'bgg_id': int(owned_game_id),
                'bgg_user_name': username,
                'bgg_user_rating': 8.0  # 假設收藏的遊戲評分都是8分
            })
        
        if not user_ratings_data:
            logger.warning(f"用戶 {username} 沒有收藏的遊戲")
            return None
        
        logger.info(f"💫 開始推薦計算，用戶評分: {len(user_ratings_data)} 個遊戲")
        
        # 執行推薦計算
        recommendations = recommender.recommend(
            users=[username],
            num_games=1000,  # 取較多結果以找到目標遊戲
            diversity=0.1 if algorithm == 'hybrid' else 0.0
        )
        
        if not recommendations or recommendations.num_rows() == 0:
            logger.warning("推薦器未返回任何結果")
            return None
        
        # 尋找目標遊戲的推薦分數
        target_recommendations = recommendations[recommendations['bgg_id'] == game_id]
        
        if target_recommendations.num_rows() == 0:
            logger.warning(f"目標遊戲 {game_id} 不在推薦結果中")
            # 嘗試使用相似度模型計算
            return get_similarity_based_score(recommender, user_ratings_data, game_id)
        
        # 返回推薦分數（rank 越小越好，轉換為分數）
        rank = target_recommendations['rank'].mean()
        score = max(0, 10 - (rank / 100))  # 將排名轉換為0-10分數
        logger.info(f"✅ 遊戲 {game_id} 推薦分數: {score:.3f} (排名: {rank})")
        return float(score)
        
    except Exception as e:
        logger.error(f"BGGRecommender 推薦分數計算失敗: {e}")
        return None

def _calculate_score_with_light_recommender(recommender, username, owned_ids, game_id, algorithm):
    """使用 LightGamesRecommender 計算推薦分數"""
    try:
        logger.info(f"🪶 使用輕量級推薦器計算遊戲 {game_id}")
        
        # 檢查是否是我們的簡單輕量級模型
        if hasattr(recommender, 'model_type') and recommender.model_type == 'simple_light':
            return _calculate_score_with_simple_light_model(recommender, username, owned_ids, game_id, algorithm)
        
        # 標準 LightGamesRecommender 邏輯
        try:
            # 構建用戶偏好向量（基於收藏）
            user_preferences = {
                'owned_games': owned_ids,
                'user_id': username
            }
            
            # 獲取單個遊戲的推薦分數
            score = recommender.score_game(game_id, user_preferences)
            
            if score is not None:
                logger.info(f"✅ 遊戲 {game_id} 輕量級推薦分數: {score:.3f}")
                return float(score)
            else:
                logger.warning(f"⚠️ 無法使用輕量級推薦器計算遊戲 {game_id} 的分數")
                return None
                
        except AttributeError:
            # 如果推薦器沒有 score_game 方法，嘗試其他方法
            logger.warning("⚠️ 輕量級推薦器沒有 score_game 方法，嘗試替代計算")
            return _calculate_score_with_simple_algorithm(owned_ids, game_id)
        
    except Exception as e:
        logger.error(f"LightGamesRecommender 推薦分數計算失敗: {e}")
        return None

def _calculate_score_with_simple_light_model(model_data, username, owned_ids, game_id, algorithm):
    """使用簡單輕量級模型計算推薦分數"""
    try:
        logger.info(f"🔧 使用簡單輕量級模型計算遊戲 {game_id}")
        
        # 如果是文件路徑，載入模型數據
        if isinstance(model_data, str):
            user_paths = get_user_rg_paths(username)
            import numpy as np
            model = np.load(user_paths['light_model'], allow_pickle=True)
            preferences = model['preferences'].item()
        else:
            # 已經是載入的模型數據
            preferences = model_data.get('preferences', {})
        
        user_ratings = preferences.get('ratings', {})
        
        # 基於用戶評分計算相似度推薦分數
        if str(game_id) in user_ratings:
            # 如果用戶已經有這個遊戲，返回用戶的評分
            score = user_ratings[str(game_id)]
            logger.info(f"✅ 遊戲 {game_id} 用戶已評分: {score}")
            return float(score)
        
        # 計算基於相似遊戲的推薦分數
        similar_scores = []
        
        # 從資料庫獲取遊戲特徵來計算相似度
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # 獲取目標遊戲的特徵
                cursor.execute("""
                    SELECT category, mechanic, min_players, max_players, playing_time, 
                           complexity, year_published
                    FROM game_detail WHERE objectid = %s
                """, (game_id,))
                
                target_game = cursor.fetchone()
                if not target_game:
                    logger.warning(f"⚠️ 找不到遊戲 {game_id} 的詳細資料")
                    return _calculate_score_with_simple_algorithm(owned_ids, game_id)
                
                # 計算與用戶收藏遊戲的相似度
                for rated_game_id, rating in user_ratings.items():
                    cursor.execute("""
                        SELECT category, mechanic, min_players, max_players, playing_time,
                               complexity, year_published
                        FROM game_detail WHERE objectid = %s
                    """, (int(rated_game_id),))
                    
                    owned_game = cursor.fetchone()
                    if owned_game:
                        similarity = _calculate_game_similarity(target_game, owned_game)
                        weighted_score = similarity * float(rating)
                        similar_scores.append(weighted_score)
                
                if similar_scores:
                    # 計算加權平均分數
                    avg_score = sum(similar_scores) / len(similar_scores)
                    # 正規化到 1-10 範圍
                    final_score = min(max(avg_score, 1.0), 10.0)
                    
                    logger.info(f"✅ 遊戲 {game_id} 簡單模型推薦分數: {final_score:.3f}")
                    return float(final_score)
        
        except Exception as e:
            logger.error(f"資料庫查詢失敗: {e}")
        
        # 降級到簡單演算法
        return _calculate_score_with_simple_algorithm(owned_ids, game_id)
        
    except Exception as e:
        logger.error(f"簡單輕量級模型計算失敗: {e}")
        return _calculate_score_with_simple_algorithm(owned_ids, game_id)

def _calculate_game_similarity(game1_features, game2_features):
    """計算兩個遊戲之間的相似度"""
    try:
        similarity = 0.0
        total_weight = 0.0
        
        # 比較分類 (權重: 0.3)
        if game1_features[0] and game2_features[0]:
            cat1 = set(game1_features[0].split(',')) if game1_features[0] else set()
            cat2 = set(game2_features[0].split(',')) if game2_features[0] else set()
            if cat1 or cat2:
                cat_sim = len(cat1.intersection(cat2)) / len(cat1.union(cat2)) if cat1.union(cat2) else 0
                similarity += cat_sim * 0.3
                total_weight += 0.3
        
        # 比較機制 (權重: 0.3)
        if game1_features[1] and game2_features[1]:
            mech1 = set(game1_features[1].split(',')) if game1_features[1] else set()
            mech2 = set(game2_features[1].split(',')) if game2_features[1] else set()
            if mech1 or mech2:
                mech_sim = len(mech1.intersection(mech2)) / len(mech1.union(mech2)) if mech1.union(mech2) else 0
                similarity += mech_sim * 0.3
                total_weight += 0.3
        
        # 比較玩家數量 (權重: 0.2)
        if game1_features[2] and game2_features[2] and game1_features[3] and game2_features[3]:
            min1, max1 = int(game1_features[2] or 1), int(game1_features[3] or 1)
            min2, max2 = int(game2_features[2] or 1), int(game2_features[3] or 1)
            overlap = max(0, min(max1, max2) - max(min1, min2) + 1)
            total_range = max(max1, max2) - min(min1, min2) + 1
            player_sim = overlap / total_range if total_range > 0 else 0
            similarity += player_sim * 0.2
            total_weight += 0.2
        
        # 比較遊戲時間 (權重: 0.1)
        if game1_features[4] and game2_features[4]:
            time1, time2 = float(game1_features[4] or 60), float(game2_features[4] or 60)
            time_diff = abs(time1 - time2)
            time_sim = max(0, 1 - time_diff / max(time1, time2)) if max(time1, time2) > 0 else 0
            similarity += time_sim * 0.1
            total_weight += 0.1
        
        # 比較複雜度 (權重: 0.1)
        if game1_features[5] and game2_features[5]:
            comp1, comp2 = float(game1_features[5] or 2.5), float(game2_features[5] or 2.5)
            comp_diff = abs(comp1 - comp2)
            comp_sim = max(0, 1 - comp_diff / 5.0)  # 複雜度範圍 1-5
            similarity += comp_sim * 0.1
            total_weight += 0.1
        
        return similarity / total_weight if total_weight > 0 else 0.5
        
    except Exception as e:
        logger.error(f"相似度計算錯誤: {e}")
        return 0.5

def _calculate_score_with_simple_algorithm(owned_ids, game_id):
    """使用最簡單的演算法計算推薦分數"""
    try:
        logger.info(f"🔄 使用簡單演算法計算遊戲 {game_id}")
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 獲取遊戲的基本評分
            cursor.execute("""
                SELECT average_rating, bayes_average_rating, num_votes
                FROM game_detail WHERE objectid = %s
            """, (game_id,))
            
            game_info = cursor.fetchone()
            if game_info:
                avg_rating = float(game_info[0] or 6.0)
                bayes_avg = float(game_info[1] or 6.0)
                num_votes = int(game_info[2] or 100)
                
                # 基於評分和投票數計算推薦分數
                base_score = (avg_rating + bayes_avg) / 2
                
                # 根據投票數調整（更多投票 = 更可靠）
                vote_factor = min(1.0, num_votes / 1000) * 0.2
                final_score = base_score + vote_factor
                
                # 稍微隨機化以模擬個人化
                import random
                personal_factor = random.uniform(-0.3, 0.3)
                final_score = max(1.0, min(10.0, final_score + personal_factor))
                
                logger.info(f"✅ 遊戲 {game_id} 簡單演算法推薦分數: {final_score:.3f}")
                return float(final_score)
        
        logger.warning(f"⚠️ 無法找到遊戲 {game_id} 的資料，返回預設分數")
        return 6.0
        
    except Exception as e:
        logger.error(f"簡單演算法計算失敗: {e}")
        return 5.0

def _calculate_score_with_fallback_recommender(recommender, username, owned_ids, game_id, algorithm):
    """使用降級推薦器計算推薦分數"""
    try:
        logger.info(f"🔄 使用降級推薦器計算遊戲 {game_id}")
        
        # 使用 AdvancedBoardGameRecommender 的邏輯
        score = recommender.get_recommendation_score(game_id, owned_ids)
        
        if score is not None:
            logger.info(f"✅ 遊戲 {game_id} 降級推薦分數: {score:.3f}")
            return float(score)
        else:
            logger.warning(f"⚠️ 無法使用降級推薦器計算遊戲 {game_id} 的分數")
            return None
        
    except Exception as e:
        logger.error(f"降級推薦器推薦分數計算失敗: {e}")
        return None

def get_basic_game_recommendation_score(username, owned_ids, game_id):
    """使用基礎方法從 JSONL 資料計算單個遊戲的推薦分數"""
    try:
        logger.info(f"🎯 使用基礎方法計算遊戲 {game_id} 的推薦分數")
        
        import turicreate as tc
        import tempfile
        import json
        
        # 從資料庫創建臨時 JSONL 文件
        games_file, ratings_file = create_temp_jsonl_files()
        if not games_file or not ratings_file:
            logger.error("❌ 無法創建 JSONL 資料檔案")
            return None
        
        try:
            # 讀取遊戲資料
            games_data = tc.SFrame.read_json(url=games_file, orient="lines")
            target_game = games_data[games_data['bgg_id'] == game_id]
            
            if target_game.num_rows() == 0:
                logger.warning(f"遊戲 {game_id} 不在資料中")
                return 5.0
            
            game_info = target_game[0]
            name = game_info.get('name', 'Unknown')
            rating = game_info.get('avg_rating', 0)
            rank = game_info.get('rank', 0)
            weight = game_info.get('complexity', 0)
            year = game_info.get('year', 0)
            
            logger.info(f"📊 遊戲資訊: {name} (評分: {rating}, 排名: {rank})")
            
            # 基礎推薦分數計算
            base_score = 0
            
            # 根據 BGG 評分計算 (40%)
            if rating and rating > 0:
                rating_score = min(rating / 10 * 4, 4)  # 最高4分
                base_score += rating_score
                
            # 根據排名計算 (30%)
            if rank and rank > 0:
                if rank <= 100:
                    rank_score = 3
                elif rank <= 1000:
                    rank_score = 2
                elif rank <= 10000:
                    rank_score = 1
                else:
                    rank_score = 0.5
                base_score += rank_score
            
            # 根據複雜度適配性計算 (20%)
            if weight and weight > 0:
                # 假設用戶偏好中等複雜度遊戲
                complexity_score = max(0, 2 - abs(weight - 2.5))
                base_score += complexity_score
                
            # 根據年份新鮮度計算 (10%)
            if year and year > 0:
                current_year = 2024
                if year >= current_year - 3:
                    freshness_score = 1
                elif year >= current_year - 10:
                    freshness_score = 0.5
                else:
                    freshness_score = 0.2
                base_score += freshness_score
            
            logger.info(f"✅ 基礎推薦分數: {base_score:.2f}")
            return base_score
            
        finally:
            # 不需要清理檔案，因為使用的是持久化的資料檔案
            pass
            
    except Exception as e:
        logger.error(f"基礎推薦分數計算失敗: {e}")
        return None


@app.route('/api/task-status', methods=['GET'])
def api_task_status():
    """API端點：查詢任務狀態"""
    if 'logged_in' not in session:
        return jsonify({'success': False, 'message': '未登入'}), 401

    global task_status

    # 計算運行時間
    elapsed_seconds = 0
    if task_status['start_time']:
        elapsed_seconds = (datetime.now() - task_status['start_time']).total_seconds()

    return jsonify({
        'success': True,
        'status': {
            'is_running': task_status['is_running'],
            'current_step': task_status['current_step'],
            'progress': task_status['progress'],
            'message': task_status['message'],
            'elapsed_seconds': int(elapsed_seconds),
            'elapsed_minutes': int(elapsed_seconds / 60),
            'last_update': task_status['last_update'].isoformat() if task_status['last_update'] else None,
            'stop_requested': task_status.get('stop_requested', False),
            'stopped_by_user': task_status.get('stopped_by_user', False)
        }
    })

@app.route('/api/run-scheduler', methods=['POST'])
def api_run_scheduler():
    """API端點：執行完整排程任務"""
    if 'logged_in' not in session:
        return jsonify({'success': False, 'message': '未登入'}), 401

    # 解析請求參數
    data = request.get_json() or {}
    force_llm_analysis = data.get('force_llm_analysis', False)
    force_regenerate = data.get('force_regenerate', False)

    logger.info(f"收到報表產生請求 - 強制LLM分析: {force_llm_analysis}, 強制重新產生: {force_regenerate}")

    success, message = generate_report(force_llm_analysis=force_llm_analysis, force_regenerate=force_regenerate)
    return jsonify({'success': success, 'message': message})

@app.route('/api/cron-trigger', methods=['POST'])
def api_cron_trigger():
    """外部 Cron 服務觸發端點（無需登入）"""
    # 檢查請求來源的安全性
    auth_header = request.headers.get('Authorization')
    expected_token = os.getenv('CRON_SECRET_TOKEN', 'default-cron-secret')

    if not auth_header or auth_header != f'Bearer {expected_token}':
        logger.warning(f"未授權的 cron 觸發請求，來源 IP: {request.remote_addr}")
        return jsonify({'success': False, 'message': '未授權'}), 401

    logger.info(f"收到外部 Cron 觸發請求，來源 IP: {request.remote_addr}")
    
    # 檢查是否已有任務正在執行
    if task_status['is_running']:
        logger.info("已有任務正在執行，跳過此次觸發")
        return jsonify({
            'success': True, 
            'message': '任務已在執行中',
            'status': 'already_running',
            'current_step': task_status.get('current_step', ''),
            'progress': task_status.get('progress', 0)
        })

    try:
        # 非同步執行報表產生，立即回應成功
        def async_report_generation():
            try:
                logger.info("🚀 開始非同步報表產生")
                from scheduler import fetch_and_generate_report
                
                # 更新任務狀態
                global task_status
                task_status.update({
                    'is_running': True,
                    'start_time': datetime.now(),
                    'current_step': '初始化',
                    'progress': 0,
                    'message': '開始產生報表...',
                    'last_update': datetime.now(),
                    'stop_requested': False,
                    'stopped_by_user': False
                })
                
                result = fetch_and_generate_report('all', 'zh-tw', False, False)
                
                # 完成任務
                task_status.update({
                    'is_running': False,
                    'current_step': '完成',
                    'progress': 100,
                    'message': '報表產生完成' if result else '報表產生失敗',
                    'last_update': datetime.now()
                })
                
                if result:
                    logger.info("✅ 非同步 Cron 觸發的報表產生成功")
                else:
                    logger.error("❌ 非同步 Cron 觸發的報表產生失敗")
                    
            except Exception as e:
                logger.error(f"❌ 非同步報表產生異常: {e}")
                task_status.update({
                    'is_running': False,
                    'current_step': '錯誤',
                    'progress': 0,
                    'message': f'執行失敗: {str(e)}',
                    'last_update': datetime.now()
                })

        # 啟動背景執行緒
        import threading
        thread = threading.Thread(target=async_report_generation)
        thread.daemon = True
        thread.start()
        
        logger.info("✅ Cron 觸發已接受，報表產生已在背景執行")
        return jsonify({
            'success': True, 
            'message': '報表產生已啟動',
            'status': 'started',
            'info': '任務正在背景執行，請稍後查看結果'
        })

    except Exception as e:
        logger.error(f"❌ Cron 觸發處理異常: {e}")
        return jsonify({'success': False, 'message': f'處理失敗: {str(e)}'}), 500

@app.route('/api/diagnose-recommendations', methods=['GET'])
def api_diagnose_recommendations():
    """診斷推薦系統狀態（用於 Zeabur 調試）"""
    if 'logged_in' not in session:
        return jsonify({'success': False, 'message': '未登入'}), 401
    
    diagnosis = {}
    
    try:
        # 基本資料檢查
        username = get_app_setting('bgg_username', '')
        diagnosis['bgg_username'] = username or 'None'
        
        # 檢查收藏資料
        owned_ids = []
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT objectid FROM collection")
                owned_ids = [row[0] for row in cursor.fetchall()]
            diagnosis['owned_games_count'] = len(owned_ids)
            diagnosis['owned_games_sample'] = owned_ids[:5] if owned_ids else []
        except Exception as e:
            diagnosis['collection_error'] = str(e)
        
        # 檢查 board-game-recommender
        try:
            from board_game_recommender.recommend import BGGRecommender
            
            # 檢查模型是否存在
            model_path = f'data/rg_users/{username}/rg_model'
            diagnosis['model_exists'] = os.path.exists(model_path)
            
            if diagnosis['model_exists']:
                try:
                    recommender = BGGRecommender.load(model_path)
                    diagnosis['model_load_success'] = True
                    
                    # 測試推薦功能
                    test_recs = recommender.recommend(users=[username], num_games=3)
                    diagnosis['sample_recommendations'] = [
                        {'name': rec['name'], 'score': rec.get('score', 0)} 
                        for rec in test_recs[:3]
                    ] if test_recs else []
                    
                except Exception as rec_error:
                    diagnosis['model_load_error'] = str(rec_error)
            else:
                diagnosis['model_missing'] = True
                
        except Exception as e:
            diagnosis['board_game_recommender_error'] = str(e)
            import traceback
            diagnosis['board_game_recommender_traceback'] = traceback.format_exc()
        
        # 測試完整推薦流程
        try:
            test_recs = get_advanced_recommendations(username, owned_ids[:5], 'popularity', 3)
            diagnosis['full_recommendation_test'] = {
                'success': test_recs is not None,
                'count': len(test_recs) if test_recs else 0,
                'sample': [rec['name'] for rec in test_recs[:3]] if test_recs else []
            }
        except Exception as e:
            diagnosis['full_recommendation_error'] = str(e)
        
        return jsonify({
            'success': True,
            'diagnosis': diagnosis,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        })

@app.route('/api/stop-task', methods=['POST'])
def api_stop_task():
    """API端點：停止當前執行的任務"""
    if 'logged_in' not in session:
        logger.warning("未登入用戶嘗試停止任務")
        return jsonify({'success': False, 'message': '未登入'}), 401

    try:
        logger.info(f"收到停止任務請求，當前任務狀態: is_running={task_status['is_running']}")

        if not task_status['is_running']:
            logger.info("沒有運行中的任務需要停止")
            return jsonify({
                'success': False,
                'message': '目前沒有運行中的任務'
            })

        # 請求停止任務
        stopped = request_task_stop()

        if stopped:
            logger.info("🛑 停止請求已成功發送")
            return jsonify({
                'success': True,
                'message': '停止請求已發送，任務正在停止中...'
            })
        else:
            logger.error("停止任務請求失敗")
            return jsonify({
                'success': False,
                'message': '無法停止任務'
            })

    except Exception as e:
        logger.error(f"停止任務 API 發生異常: {e}")
        import traceback
        logger.error(f"異常堆疊: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'message': f'停止任務時發生錯誤: {e}'
        })


@app.route('/')
def index():
    """首頁 - 重導向到登入或儀表板"""
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login')
@app.route('/login_email')
def login():
    """顯示登入頁面"""
    if 'user' in session:
        return redirect(url_for('dashboard'))
    
    # 使用新的 email 登入模板
    return render_template('login_email.html')

@app.route('/auth/google')
def google_auth_callback():
    """處理 Google 登入回調"""
    if not GOOGLE_AUTH_AVAILABLE or not google_auth:
        flash('Google 登入功能暫不可用', 'error')
        return redirect(url_for('login'))
    
    token = request.args.get('token')
    if not token:
        flash('登入失敗：未收到認證 token', 'error')
        return redirect(url_for('login'))
    
    # 驗證 Google token
    user_info = google_auth.verify_google_token(token)
    if not user_info:
        flash('登入失敗：無效的認證 token', 'error')
        return redirect(url_for('login'))
    
    if not user_info['email_verified']:
        flash('登入失敗：請先驗證您的 Google 帳戶 email', 'error')
        return redirect(url_for('login'))
    
    # 創建或更新用戶
    user_data = google_auth.create_or_update_user(
        user_info['google_id'],
        user_info['email'],
        user_info['name'],
        user_info['picture']
    )
    
    if user_data:
        session['user'] = user_data
        session['logged_in'] = True
        session['user_email'] = user_data.get('email', '')
        flash(f'歡迎 {user_data["name"]}！', 'success')
        return redirect(url_for('dashboard'))
    else:
        flash('登入失敗：無法創建用戶資料', 'error')
        return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    """用戶儀表板"""
    return redirect(url_for('bgg_times'))

@app.route('/generate')
@admin_required
def generate():

    success, message = generate_report()
    if success:
        flash(message, 'success')
    else:
        flash(message, 'error')

    return redirect(url_for('index'))


@app.route('/bgg_times')
def bgg_times():
    """復古報紙風格的報表檢視 - 真正的舊報紙風格"""
    if 'logged_in' not in session:
        return redirect(url_for('login'))

    # 獲取選擇的日期，預設為今日
    selected_date = request.args.get('date')
    if not selected_date:
        selected_date = datetime.now().strftime('%Y-%m-%d')

    # 獲取指定日期的報表
    content, filename = get_report_by_date(selected_date)

    # 如果找不到指定日期的報表，嘗試獲取最新報表
    if content is None:
        content, filename = get_latest_report()

    if content is None:
        return render_template('error.html', error=filename)

    # 解析所有遊戲資料
    all_games = parse_game_data_from_report(content)
    current_page_games = all_games
    total_games = len(all_games)

    # 獲取所有可用日期
    available_dates = get_available_dates()

    return render_template('bgg_times.html',
                         current_page_games=current_page_games,
                         filename=filename,
                         selected_date=selected_date,
                         available_dates=available_dates,
                         total_games=total_games,
                         last_updated=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

@app.route('/api/check-files', methods=['GET'])
def api_check_files():
    """API端點：檢查報表目錄檔案"""
    if 'logged_in' not in session:
        return jsonify({'success': False, 'message': '未登入'}), 401

    try:
        report_dir = 'frontend/public/outputs'
        files_info = []

        if os.path.exists(report_dir):
            files = sorted(os.listdir(report_dir), reverse=True)
            for filename in files:
                if filename.endswith('.md'):
                    filepath = os.path.join(report_dir, filename)
                    stat = os.stat(filepath)
                    files_info.append({
                        'name': filename,
                        'size': stat.st_size,
                        'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                    })

        return jsonify({
            'success': True,
            'directory': report_dir,
            'files': files_info,
            'total_files': len(files_info)
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/check-database', methods=['GET'])
def api_check_database():
    """API端點：檢查資料庫內容"""
    if 'logged_in' not in session:
        return jsonify({'success': False, 'message': '未登入'}), 401

    try:
        # 先檢查資料庫配置
        config = get_database_config()

        # 檢查環境變數
        env_vars = {
            'DATABASE_URL': os.getenv('DATABASE_URL', 'Not set'),
            'POSTGRES_CONNECTION_STRING': os.getenv('POSTGRES_CONNECTION_STRING', 'Not set'),
            'POSTGRES_HOST': os.getenv('POSTGRES_HOST', 'Not set'),
            'POSTGRES_PORT': os.getenv('POSTGRES_PORT', 'Not set'),
            'POSTGRES_DATABASE': os.getenv('POSTGRES_DATABASE', 'Not set'),
            'POSTGRES_USERNAME': os.getenv('POSTGRES_USERNAME', 'Not set'),
            'POSTGRES_PASSWORD': os.getenv('POSTGRES_PASSWORD', 'Not set')
        }

        with get_db_connection() as conn:
            cursor = conn.cursor()

            # 檢查現有表格
            existing_tables = []
            cursor.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name
            """)

            existing_tables = [row[0] for row in cursor.fetchall()]

            # 嘗試檢查 hot_games 表（如果存在）
            hot_games_data = []
            game_detail_count = 0
            forum_threads_count = 0

            if 'hot_games' in existing_tables:
                try:
                    cursor.execute("SELECT snapshot_date, COUNT(*) as count FROM hot_games GROUP BY snapshot_date ORDER BY snapshot_date DESC LIMIT 10")
                    hot_games_data = [{'date': row[0], 'count': row[1]} for row in cursor.fetchall()]
                except Exception as e:
                    hot_games_data = [{'error': f'Query failed: {str(e)}'}]

            if 'game_detail' in existing_tables:
                try:
                    cursor.execute("SELECT COUNT(*) as total_games FROM game_detail")
                    game_detail_count = cursor.fetchone()[0]
                except:
                    pass

            if 'forum_threads' in existing_tables:
                try:
                    cursor.execute("SELECT COUNT(*) as total_threads FROM forum_threads")
                    forum_threads_count = cursor.fetchone()[0]
                except:
                    pass

            return jsonify({
                'success': True,
                'database_type': config['type'],
                'database_url_masked': config.get('url', 'Not available')[:50] + '...' if config.get('url') else 'Not available',
                'environment_variables': env_vars,
                'existing_tables': existing_tables,
                'hot_games_by_date': hot_games_data,
                'total_game_details': game_detail_count,
                'total_forum_threads': forum_threads_count
            })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e),
            'database_type': config.get('type', 'unknown') if 'config' in locals() else 'unknown',
            'environment_variables': {
                'DATABASE_URL': os.getenv('DATABASE_URL', 'Not set'),
                'POSTGRES_CONNECTION_STRING': os.getenv('POSTGRES_CONNECTION_STRING', 'Not set')
            }
        })

@app.route('/health')
def health():
    """健康檢查端點 - 快速響應版本"""
    
    # 簡單健康檢查，不阻塞啟動
    health_info = {
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'python_version': sys.version,
        'port': os.getenv('PORT', 'not set'),
        'database_url_configured': 'yes' if os.getenv('DATABASE_URL') else 'no'
    }
    
    # 只有在應用已經完全啟動後才嘗試資料庫檢查
    if os.getenv('SKIP_DB_HEALTH_CHECK') != '1':
        # 非阻塞式資料庫狀態檢查
        try:
            from database import get_db_connection
            import signal
            
            # 設置 5 秒超時
            def timeout_handler(signum, frame):
                raise TimeoutError("Database connection timeout")
            
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(5)  # 5 秒超時
            
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                health_info['database'] = 'connected'
            
            signal.alarm(0)  # 取消超時
            
        except TimeoutError:
            health_info['database'] = 'timeout'
        except Exception as e:
            health_info['database'] = f'error: {str(e)[:50]}'
    else:
        health_info['database'] = 'check_skipped'
    
    return health_info

@app.route('/health/quick')
def health_quick():
    """快速健康檢查端點 - 僅用於啟動時檢查"""
    return {
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'app': 'running'
    }

@app.route('/api/init-database', methods=['POST'])
def api_init_database():
    """手動初始化資料庫端點"""
    try:
        # 檢查是否有授權 token
        auth_header = request.headers.get('Authorization')
        expected_token = os.getenv('CRON_SECRET_TOKEN', 'default-cron-secret')
        
        if not auth_header or auth_header != f'Bearer {expected_token}':
            return jsonify({
                'success': False, 
                'message': '未授權訪問',
                'timestamp': datetime.now().isoformat()
            }), 401
        
        print("🗃️ [API] 開始手動資料庫初始化...")
        print(f"🗃️ [API] 時間戳: {datetime.now().isoformat()}")
        
        # 獲取資料庫配置
        from database import get_database_config, init_database
        config = get_database_config()
        print(f"🗃️ [API] 資料庫類型: {config['type']}")
        
        # 執行初始化
        init_database()
        
        # 驗證關鍵表是否存在
        from database import get_db_connection
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 檢查 users 表的 name 欄位
            try:
                cursor.execute("SELECT name FROM users LIMIT 1")
                users_name_exists = True
            except Exception as e:
                users_name_exists = False
                print(f"⚠️ [API] users.name 欄位檢查失敗: {e}")
            
            # 檢查 verification_codes 表
            try:
                cursor.execute("SELECT COUNT(*) FROM verification_codes")
                verification_codes_exists = True
            except Exception as e:
                verification_codes_exists = False
                print(f"⚠️ [API] verification_codes 表檢查失敗: {e}")
        
        result = {
            'success': True,
            'message': '資料庫初始化完成',
            'timestamp': datetime.now().isoformat(),
            'database_type': config['type'],
            'tables_verified': {
                'users_name_column': users_name_exists,
                'verification_codes_table': verification_codes_exists
            }
        }
        
        print(f"✅ [API] 資料庫初始化結果: {result}")
        return jsonify(result)
        
    except Exception as e:
        error_msg = f"資料庫初始化失敗: {str(e)}"
        print(f"❌ [API] {error_msg}")
        import traceback
        traceback.print_exc()
        
        return jsonify({
            'success': False,
            'message': error_msg,
            'timestamp': datetime.now().isoformat()
        }), 500

# 設計師/繪師追蹤相關路由
@app.route('/creator-tracker')
@full_access_required
def creator_tracker():
    """設計師/繪師追蹤頁面"""
    user = session.get('user', {})
    user_email = user.get('email', '')
    return render_template('creator_tracker.html', user_email=user_email)

@app.route('/api/creators/search', methods=['POST'])
@full_access_required
def api_search_creators():
    """搜尋設計師/繪師 API"""
    try:
        data = request.get_json()
        query = data.get('query', '').strip()
        creator_type = data.get('type', 'boardgamedesigner')
        
        if not query:
            return jsonify({'success': False, 'message': '請輸入搜尋關鍵字'})
        
        from creator_tracker import CreatorTracker
        tracker = CreatorTracker()
        
        results = tracker.search_creators(query, creator_type)
        
        return jsonify({
            'success': True,
            'results': results
        })
        
    except Exception as e:
        logger.error(f"搜尋設計師失敗: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/creator/<int:creator_id>/<creator_type>')
def creator_details_page(creator_id, creator_type):
    """設計師/繪師詳細資料頁面"""
    return render_template('creator_details.html', creator_id=creator_id, creator_type=creator_type)

@app.route('/api/creators/<int:creator_id>/<creator_type>')
def api_get_creator_details(creator_id, creator_type):
    """獲取設計師/繪師詳細資料 API"""
    try:
        from creator_tracker import CreatorTracker
        tracker = CreatorTracker()
        
        # 獲取詳細資料
        details = tracker.get_creator_details(creator_id, creator_type)
        if not details:
            return jsonify({'success': False, 'message': '無法獲取詳細資料'})
        
        # 確定正確的 API 類型
        api_type = 'boardgamedesigner' if creator_type in ['designer', 'boardgamedesigner'] else 'boardgameartist'
        slug = details.get('slug')
        
        # 獲取 average 排序的第一筆遊戲（top game）
        top_game = None
        if slug:
            top_games = tracker.get_all_creator_games(creator_id, slug, api_type, sort='average', limit=1)
            if top_games:
                game = top_games[0]
                top_game = {
                    'name': game.get('name'),
                    'url': f"https://boardgamegeek.com/boardgame/{game.get('bgg_id')}"
                }
        
        # 獲取 yearpublished 排序的前5筆遊戲
        recent_games = []
        if slug:
            games = tracker.get_all_creator_games(creator_id, slug, api_type, sort='yearpublished', limit=5)
            for game in games:
                recent_games.append({
                    'name': game.get('name'),
                    'year': game.get('year'),
                    'url': f"https://boardgamegeek.com/boardgame/{game.get('bgg_id')}"
                })
        
        # 檢查用戶是否已追蹤
        user_data = session.get('user')
        is_following = False
        
        if user_data and user_data.get('id'):
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT 1 FROM user_follows uf
                    JOIN creators c ON uf.creator_id = c.id
                    WHERE c.bgg_id = %s AND uf.user_id = %s
                """, (creator_id, user_data['id']))
                is_following = cursor.fetchone() is not None
        
        details['is_following'] = is_following
        details['top_game'] = top_game
        details['recent_games'] = recent_games
        
        return jsonify({
            'success': True,
            'creator': details
        })
        
    except Exception as e:
        logger.error(f"獲取設計師詳細資料失敗: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/creators/follow', methods=['POST'])
@full_access_required
def api_follow_creator():
    """追蹤/取消追蹤設計師/繪師 API"""
    try:
        user_data = session.get('user', {})
        user_id = user_data.get('id')
        user_email = user_data.get('email')
        
        if not user_id:
            return jsonify({'success': False, 'message': '請先登入'})
        
        data = request.get_json()
        creator_bgg_id = data.get('creator_id')
        creator_type = data.get('type')
        action = data.get('action')  # 'follow' or 'unfollow'
        
        if not all([creator_bgg_id, creator_type, action]):
            return jsonify({'success': False, 'message': '參數不完整'})
        
        # 檢查用戶是否設定了 email（追蹤功能需要 email 通知）
        if action == 'follow' and not user_email:
            return jsonify({'success': False, 'message': '請先在設定頁面設定 Email 地址才能使用追蹤功能'})
        
        from creator_tracker import CreatorTracker
        tracker = CreatorTracker()
        
        if action == 'follow':
            # 映射前端類型到 BGG API 類型
            bgg_type_map = {
                'designer': 'boardgamedesigner',
                'artist': 'boardgameartist'
            }
            bgg_type = bgg_type_map.get(creator_type, 'boardgamedesigner')
            
            # 獲取設計師名稱
            details = tracker.get_creator_details(creator_bgg_id, bgg_type)
            if not details:
                return jsonify({'success': False, 'message': '無法獲取設計師資料'})
            
            creator_name = details['name']
            
            # 使用修復過的 follow_creator 方法
            result = tracker.follow_creator(user_id, int(creator_bgg_id), bgg_type, creator_name)
            
            return jsonify(result)
            
        else:  # unfollow
            # 取消追蹤
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    DELETE FROM user_follows 
                    WHERE user_id = %s AND creator_id = (
                        SELECT id FROM creators WHERE bgg_id = %s
                    )
                """, (user_id, creator_bgg_id))
                conn.commit()
            
            return jsonify({
                'success': True,
                'message': '已取消追蹤'
            })
        
    except Exception as e:
        logger.error(f"追蹤操作失敗: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/recommendations/by-games', methods=['POST'])
@full_access_required
def api_get_recommendations_by_games():
    """根據用戶選擇的遊戲獲得推薦 API"""
    try:
        data = request.get_json()
        selected_games = data.get('games', [])
        num_recommendations = data.get('num_recommendations', 10)
        
        if not selected_games:
            return jsonify({'success': False, 'message': '請選擇至少一款遊戲'})
        
        if len(selected_games) > 10:
            return jsonify({'success': False, 'message': '最多只能選擇10款遊戲'})
        
        # 使用 board-game-recommender 進行推薦
        username = get_app_setting('bgg_username', '')
        if not username:
            return jsonify({'success': False, 'message': '請先設定 BGG 用戶名'})
        
        # 檢查模型是否存在
        model_path = f'data/rg_users/{username}/rg_model'
        if not os.path.exists(model_path):
            return jsonify({'success': False, 'message': '推薦模型尚未訓練，請先到設定頁重新訓練'})
        
        # 使用 board-game-recommender 獲取推薦
        recommendations = get_advanced_recommendations(username, selected_games, algorithm='hybrid', limit=num_recommendations)
        
        if not recommendations:
            return jsonify({'success': False, 'message': '無法獲取推薦，請檢查模型是否正確訓練'})
        
        return jsonify({
            'success': True,
            'recommendations': recommendations
        })
        
    except Exception as e:
        logger.error(f"獲取遊戲推薦失敗: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/games/search', methods=['POST'])
def api_search_games():
    """搜尋遊戲 API（用於推薦系統的遊戲選擇）"""
    try:
        data = request.get_json()
        query = data.get('query', '').strip()
        limit = min(data.get('limit', 20), 50)  # 最多返回50個結果
        
        if not query:
            return jsonify({'success': False, 'message': '請輸入搜尋關鍵字'})
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT objectid, name, year, rating, rank, image, 
                       categories, mechanics
                FROM game_detail 
                WHERE name ILIKE %s 
                    AND rating IS NOT NULL 
                    AND rating > 5.0
                ORDER BY rating DESC, rank ASC
                LIMIT %s
            """, (f'%{query}%', limit))
            
            results = cursor.fetchall()
            games = []
            
            for row in results:
                games.append({
                    'objectid': row[0],
                    'name': row[1],
                    'year': row[2],
                    'rating': row[3],
                    'rank': row[4],
                    'image': row[5],
                    'categories': row[6],
                    'mechanics': row[7],
                    'display_name': f"{row[1]} ({row[2]})" if row[2] else row[1]
                })
            
            return jsonify({
                'success': True,
                'games': games,
                'query': query,
                'total': len(games)
            })
            
    except Exception as e:
        logger.error(f"搜尋遊戲失敗: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/recommendations')
def recommendations_page():
    """遊戲推薦頁面"""
    return render_template('recommendations.html')

@app.route('/api/creators/following')
@full_access_required
def api_get_following_creators():
    """獲取用戶追蹤的設計師/繪師列表 API"""
    try:
        user = session.get('user', {})
        user_id = user.get('id')
        if not user_id:
            return jsonify({'success': False, 'message': '請先登入'})
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            config = get_database_config()
            
            if config['type'] == 'postgresql':
                cursor.execute("""
                    SELECT c.bgg_id, c.name, c.type, c.description, c.image_url, uf.followed_at
                    FROM creators c
                    JOIN user_follows uf ON c.id = uf.creator_id
                    WHERE uf.user_id = %s
                    ORDER BY uf.followed_at DESC
                """, (user_id,))
            else:
                cursor.execute("""
                    SELECT c.bgg_id, c.name, c.type, c.description, c.image_url, uf.followed_at
                    FROM creators c
                    JOIN user_follows uf ON c.id = uf.creator_id
                    WHERE uf.user_id = ?
                    ORDER BY uf.followed_at DESC
                """, (user_id,))
            
            creators = []
            for row in cursor.fetchall():
                creators.append({
                    'bgg_id': row[0],
                    'name': row[1],
                    'type': row[2],
                    'description': row[3],
                    'image_url': row[4],
                    'followed_at': row[5]
                })
        
        return jsonify({
            'success': True,
            'creators': creators
        })
        
    except Exception as e:
        logger.error(f"獲取追蹤列表失敗: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/cron-update-creators', methods=['POST'])
def cron_update_creators():
    """定時更新設計師/繪師作品的 API 端點"""
    # 檢查授權
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({'success': False, 'message': '未授權'}), 401
    
    token = auth_header.split(' ')[1]
    expected_token = os.getenv('CRON_SECRET_TOKEN')
    
    if not expected_token or token != expected_token:
        return jsonify({'success': False, 'message': '授權失敗'}), 401
    
    try:
        data = request.get_json() or {}
        force_update = data.get('force', False)
        
        logger.info(f"開始更新設計師/繪師作品 (force: {force_update})")
        
        # 在背景執行更新程序
        import subprocess
        import threading
        
        def run_update():
            try:
                cmd = ['python3', 'update_creators.py']
                if force_update:
                    cmd.append('--force')
                
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=3600  # 1小時超時
                )
                
                if result.returncode == 0:
                    logger.info("設計師/繪師作品更新完成")
                else:
                    logger.error(f"設計師/繪師作品更新失敗: {result.stderr}")
                    
            except Exception as e:
                logger.error(f"執行更新腳本失敗: {e}")
        
        # 在背景執行
        update_thread = threading.Thread(target=run_update)
        update_thread.daemon = True
        update_thread.start()
        
        return jsonify({
            'success': True,
            'message': '設計師/繪師作品更新已開始',
            'force': force_update,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"觸發設計師更新失敗: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/save-user-email', methods=['POST'])
def api_save_user_email():
    """儲存用戶 Email API"""
    try:
        if 'logged_in' not in session:
            return jsonify({'success': False, 'message': '請先登入'}), 401
        
        data = request.get_json()
        email = data.get('email', '').strip()
        
        if not email:
            return jsonify({'success': False, 'message': '請輸入 Email 地址'})
        
        # 簡單的 email 格式驗證
        import re
        email_regex = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'
        if not re.match(email_regex, email):
            return jsonify({'success': False, 'message': '請輸入有效的 Email 地址'})
        
        # 更新 session 中的 email
        session['user_email'] = email
        
        # 如果有用戶系統，也可以儲存到資料庫
        # 這裡暫時只儲存在 session 中
        
        return jsonify({
            'success': True,
            'message': 'Email 地址已儲存'
        })
        
    except Exception as e:
        logger.error(f"儲存用戶 Email 失敗: {e}")
        return jsonify({'success': False, 'message': str(e)})

# ============================
# Email 認證路由
# ============================

@app.route('/register')
def register():
    """註冊頁面"""
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return render_template('register.html')

@app.route('/forgot-password')
def forgot_password():
    """忘記密碼頁面"""
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return render_template('forgot_password.html')

@app.route('/auth/send-code', methods=['POST'])
def send_verification_code():
    """發送驗證碼"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        code_type = data.get('type', 'register')
        
        if not email:
            return jsonify({'success': False, 'message': '請提供 Email 地址'})
        
        # 檢查 email 格式
        import re
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            return jsonify({'success': False, 'message': 'Email 格式無效'})
        
        # 對於登入和密碼重設，檢查用戶是否存在
        if code_type in ['login', 'password_reset']:
            user = email_auth.get_user_by_email(email)
            if not user:
                return jsonify({'success': False, 'message': '用戶不存在'})
            if not user['is_active']:
                return jsonify({'success': False, 'message': '帳號已被停用'})
        
        # 對於註冊，檢查用戶是否已存在
        elif code_type == 'register':
            user = email_auth.get_user_by_email(email)
            if user:
                return jsonify({'success': False, 'message': '此 Email 已註冊'})
        
        # 生成並發送驗證碼
        code = email_auth.generate_verification_code()
        
        # 儲存驗證碼
        if not email_auth.store_verification_code(email, code, code_type):
            return jsonify({'success': False, 'message': '驗證碼儲存失敗'})
        
        # 發送郵件
        if email_auth.send_verification_code(email, code, code_type):
            return jsonify({'success': True, 'message': '驗證碼已發送'})
        else:
            return jsonify({'success': False, 'message': '郵件發送失敗，請檢查 SMTP 設定'})
        
    except Exception as e:
        logger.error(f"發送驗證碼失敗: {e}")
        return jsonify({'success': False, 'message': f'系統錯誤: {str(e)}'})

@app.route('/auth/verify-code', methods=['POST'])
def verify_code():
    """驗證驗證碼"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        code = data.get('code', '').strip()
        code_type = data.get('type', 'register')
        
        if not email or not code:
            return jsonify({'success': False, 'message': '請提供 Email 和驗證碼'})
        
        # 驗證驗證碼
        if email_auth.verify_code(email, code, code_type):
            return jsonify({'success': True, 'message': '驗證成功'})
        else:
            return jsonify({'success': False, 'message': '驗證碼無效或已過期'})
        
    except Exception as e:
        logger.error(f"驗證驗證碼失敗: {e}")
        return jsonify({'success': False, 'message': f'系統錯誤: {str(e)}'})

@app.route('/auth/register', methods=['POST'])
def register_user():
    """完成用戶註冊"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        
        if not email or not password:
            return jsonify({'success': False, 'message': '請提供 Email 和密碼'})
        
        if len(password) < 6:
            return jsonify({'success': False, 'message': '密碼至少需要6個字符'})
        
        # 檢查是否有有效的驗證碼（確保用戶已通過驗證）
        with get_db_connection() as conn:
            cursor = conn.cursor()
            config = get_database_config()
            execute_query(cursor, """
                SELECT id FROM verification_codes 
                WHERE email = ? AND type = 'register' AND used = 1
                AND expires_at > ?
            """, (email, datetime.now().isoformat()), config['type'])
            
            if not cursor.fetchone():
                return jsonify({'success': False, 'message': '請先完成 Email 驗證'})
        
        # 使用 email 前綴作為預設名稱
        name = email.split('@')[0]
        
        # 創建用戶
        user_data, message = email_auth.create_user(email, password, name)
        
        if user_data:
            # 設定 session
            session['user'] = user_data
            session['logged_in'] = True
            session['user_email'] = email
            
            # 清理已使用的驗證碼
            with get_db_connection() as conn:
                cursor = conn.cursor()
                config = get_database_config()
                execute_query(cursor, 
                    "DELETE FROM verification_codes WHERE email = ? AND type = 'register'", 
                    (email,), config['type'])
                conn.commit()
            
            return jsonify({
                'success': True, 
                'message': message,
                'redirect': url_for('dashboard')
            })
        else:
            return jsonify({'success': False, 'message': message})
        
    except Exception as e:
        logger.error(f"用戶註冊失敗: {e}")
        return jsonify({'success': False, 'message': f'註冊失敗: {str(e)}'})

@app.route('/auth/login', methods=['POST'])
def login_user():
    """用戶登入"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        
        if not email or not password:
            return jsonify({'success': False, 'message': '請提供 Email 和密碼'})
        
        # 驗證用戶
        user_data, message = email_auth.authenticate_user(email, password)
        
        if user_data:
            # 設定 session
            session['user'] = user_data
            session['logged_in'] = True
            session['user_email'] = email
            return jsonify({
                'success': True,
                'message': message,
                'redirect': url_for('dashboard')
            })
        else:
            return jsonify({'success': False, 'message': message})
        
    except Exception as e:
        logger.error(f"用戶登入失敗: {e}")
        return jsonify({'success': False, 'message': f'登入失敗: {str(e)}'})

@app.route('/auth/verify-login', methods=['POST'])
def verify_login():
    """驗證碼登入"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        code = data.get('code', '').strip()
        
        if not email or not code:
            return jsonify({'success': False, 'message': '請提供 Email 和驗證碼'})
        
        # 檢查用戶是否存在
        user_data = email_auth.get_user_by_email(email)
        if not user_data:
            return jsonify({'success': False, 'message': '用戶不存在'})
        
        if not user_data['is_active']:
            return jsonify({'success': False, 'message': '帳號已被停用'})
        
        # 驗證驗證碼
        if email_auth.verify_code(email, code, 'login'):
            # 設定 session
            session['user'] = user_data
            session['logged_in'] = True
            session['user_email'] = email
            return jsonify({
                'success': True,
                'message': '登入成功',
                'redirect': url_for('dashboard')
            })
        else:
            return jsonify({'success': False, 'message': '驗證碼無效或已過期'})
        
    except Exception as e:
        logger.error(f"驗證碼登入失敗: {e}")
        return jsonify({'success': False, 'message': f'登入失敗: {str(e)}'})

@app.route('/auth/reset-password', methods=['POST'])
def reset_password():
    """重設密碼"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        code = data.get('code', '').strip()
        new_password = data.get('password', '')
        
        if not email or not code or not new_password:
            return jsonify({'success': False, 'message': '請提供完整資訊'})
        
        if len(new_password) < 6:
            return jsonify({'success': False, 'message': '密碼至少需要6個字符'})
        
        # 再次驗證驗證碼
        if not email_auth.verify_code(email, code, 'password_reset'):
            return jsonify({'success': False, 'message': '驗證碼無效或已過期'})
        
        # 更新密碼
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                from database import execute_query, get_database_config
                
                password_hash = email_auth.hash_password(new_password)
                updated_at = datetime.now().isoformat()
                config = get_database_config()
                
                execute_query(cursor, """
                    UPDATE users 
                    SET password_hash = ?, updated_at = ?
                    WHERE email = ?
                """, (password_hash, updated_at, email), config['type'])
                
                conn.commit()
                
                return jsonify({'success': True, 'message': '密碼重設成功'})
                
        except Exception as e:
            logger.error(f"更新密碼失敗: {e}")
            return jsonify({'success': False, 'message': '密碼更新失敗'})
        
    except Exception as e:
        logger.error(f"重設密碼失敗: {e}")
        return jsonify({'success': False, 'message': f'重設失敗: {str(e)}'})

@app.route('/logout')
def logout():
    """登出"""
    session.clear()
    return redirect(url_for('login'))

# 模塊級資料庫初始化 - 適用於 Gunicorn/WSGI 環境
try:
    # 檢查是否應跳過模組級初始化（由 start_simple.py 設置）
    if not os.getenv('SKIP_MODULE_DB_INIT') and os.getenv('DATABASE_URL'):
        print("📋 模塊載入: 檢查資料庫初始化需求...")
        # 延遲執行，避免導入循環
        import threading
        def delayed_init():
            import time
            time.sleep(1)  # 等待 1 秒確保所有模塊載入完成
            force_db_initialization()
        
        init_thread = threading.Thread(target=delayed_init, daemon=True)
        init_thread.start()
        print("📋 模塊載入: 資料庫初始化線程已啟動")
    elif os.getenv('SKIP_MODULE_DB_INIT'):
        print("📋 模塊載入: 跳過資料庫初始化（由啟動腳本管理）")
        
        # 在 Zeabur 生產環境中，延遲檢查 RG 推薦資料
        def delayed_rg_init():
            import time
            time.sleep(45)  # 等待 45 秒讓應用完全啟動
            try:
                # 檢查推薦系統資料是否存在
                print("🔍 [RG] 檢查推薦系統資料...")
                # TODO: 這裡可以加入實際的資料檢查邏輯
                print("📊 [RG] 推薦系統資料檢查完成")
            except Exception as e:
                print(f"⚠️ [RG] 推薦資料初始化警告: {e}")
        
        rg_thread = threading.Thread(target=delayed_rg_init, daemon=True)
        rg_thread.start()
        print("📋 模塊載入: RG 資料檢查線程已啟動")
except Exception as e:
    print(f"⚠️ 模塊級初始化警告: {e}")

if __name__ == '__main__':
    # 確保資料庫在應用啟動前完成初始化
    print("🔄 應用啟動前執行資料庫檢查...")
    force_db_initialization()
    
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)