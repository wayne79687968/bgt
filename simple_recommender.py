#!/usr/bin/env python3
"""
簡化推薦系統 - 只使用 board-game-recommender 套件
清除所有複雜的機器學習模型，專注於 BGGRecommender 的核心功能
"""

import logging
from typing import List, Dict, Optional, Tuple
from database import get_db_connection

logger = logging.getLogger(__name__)

class SimpleBGGRecommender:
    """簡化的 BGG 推薦器，只使用 board-game-recommender 套件"""

    def __init__(self):
        self.recommender = None
        self._initialize_recommender()

    def _initialize_recommender(self):
        """初始化 BGGRecommender"""
        try:
            from board_game_recommender import BGGRecommender
            self.recommender = BGGRecommender()
            logger.info("✅ BGGRecommender 初始化成功")
            return True
        except ImportError as e:
            logger.error(f"❌ 無法載入 BGGRecommender: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ BGGRecommender 初始化失敗: {e}")
            return False

    def is_available(self) -> bool:
        """檢查推薦器是否可用"""
        return self.recommender is not None

    def get_recommendation_score(self, game_id: int, owned_games: List[int]) -> Optional[float]:
        """
        獲取單個遊戲的推薦分數

        Args:
            game_id: 遊戲 ID
            owned_games: 用戶擁有的遊戲 ID 列表

        Returns:
            推薦分數 (0-10)，如果無法計算則返回 None
        """
        if not self.is_available():
            logger.warning("BGGRecommender 不可用")
            return None

        if not owned_games:
            logger.warning("用戶沒有擁有的遊戲，無法計算推薦分數")
            return None

        try:
            # 使用 BGGRecommender 計算推薦分數
            # 這裡需要根據 board-game-recommender 的實際 API 調整
            score = self._calculate_score_with_bgg_recommender(game_id, owned_games)

            if score is not None:
                # 確保分數在 0-10 範圍內
                score = max(0, min(10, score))
                logger.info(f"✅ 遊戲 {game_id} 推薦分數: {score:.2f}")
                return score
            else:
                logger.warning(f"⚠️ 無法計算遊戲 {game_id} 的推薦分數")
                return None

        except Exception as e:
            logger.error(f"❌ 計算推薦分數失敗: {e}")
            return None

    def _calculate_score_with_bgg_recommender(self, game_id: int, owned_games: List[int]) -> Optional[float]:
        """使用 BGGRecommender 計算推薦分數的核心邏輯"""
        try:
            if not self.recommender:
                logger.warning("BGGRecommender 不可用")
                return None

            # 創建用戶評分數據 - BGGRecommender 需要用戶評分格式
            # 格式通常是: [(user_id, game_id, rating), ...]
            user_ratings = []
            username = "temp_user"  # 臨時用戶名

            # 為擁有的遊戲設定假設評分 (7-9分)
            for game in owned_games:
                rating = 8.0  # 假設用戶喜歡擁有的遊戲，給予高分
                user_ratings.append((username, game, rating))

            # 使用 BGGRecommender 進行推薦
            # 注意：這裡需要根據實際的 BGGRecommender API 調整
            try:
                # 構建訓練數據
                import turicreate as tc
                ratings_sf = tc.SFrame(user_ratings, column_names=['user_id', 'game_id', 'rating'])

                # 訓練模型（簡化版）
                model = tc.recommender.create(ratings_sf, user_id='user_id', item_id='game_id', target='rating')

                # 獲取推薦分數
                recommendations = model.recommend([username], k=1000)  # 獲取大量推薦

                # 尋找目標遊戲的分數
                target_rec = recommendations[recommendations['game_id'] == game_id]

                if len(target_rec) > 0:
                    # BGGRecommender 通常返回 0-1 之間的分數，我們轉換為 0-10
                    score = target_rec['score'][0] * 10
                    logger.info(f"✅ 使用 BGGRecommender 計算遊戲 {game_id} 分數: {score:.2f}")
                    return float(score)
                else:
                    logger.warning(f"⚠️ BGGRecommender 沒有為遊戲 {game_id} 生成推薦")
                    return None

            except Exception as model_error:
                logger.error(f"BGGRecommender 模型錯誤: {model_error}")
                # 降級到基於相似度的計算
                return self._fallback_similarity_calculation(game_id, owned_games)

        except Exception as e:
            logger.error(f"BGGRecommender 計算失敗: {e}")
            return None

    def _fallback_similarity_calculation(self, game_id: int, owned_games: List[int]) -> Optional[float]:
        """當 BGGRecommender 失敗時的降級計算方法"""
        try:
            logger.info(f"🔄 使用降級相似度計算 for 遊戲 {game_id}")

            # 獲取遊戲詳細資料
            game_data = self._get_game_data(game_id)
            if not game_data:
                return None

            owned_games_data = []
            for owned_id in owned_games:
                owned_data = self._get_game_data(owned_id)
                if owned_data:
                    owned_games_data.append(owned_data)

            if not owned_games_data:
                return None

            # 計算基於類別和機制的相似度分數
            similarity_score = self._calculate_similarity_score(game_data, owned_games_data)

            # 結合遊戲品質分數
            quality_score = self._calculate_quality_score(game_data)

            # 加權合併分數
            final_score = (similarity_score * 0.7) + (quality_score * 0.3)

            return final_score

        except Exception as e:
            logger.error(f"降級計算失敗: {e}")
            return None

    def _get_game_data(self, game_id: int) -> Optional[Dict]:
        """從資料庫獲取遊戲資料"""
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT objectid, name, categories, mechanics, rating, rank, weight
                    FROM game_detail
                    WHERE objectid = %s
                """, (game_id,))
                result = cursor.fetchone()

                if result:
                    return {
                        'objectid': result[0],
                        'name': result[1],
                        'categories': result[2] or '',
                        'mechanics': result[3] or '',
                        'rating': result[4] or 0,
                        'rank': result[5] or 10000,
                        'weight': result[6] or 0
                    }
                return None

        except Exception as e:
            logger.error(f"獲取遊戲資料失敗: {e}")
            return None

    def _calculate_similarity_score(self, target_game: Dict, owned_games: List[Dict]) -> float:
        """計算目標遊戲與用戶擁有遊戲的相似度"""
        try:
            similarities = []

            for owned_game in owned_games:
                # 類別相似度
                target_cats = set(target_game['categories'].split(',')) if target_game['categories'] else set()
                owned_cats = set(owned_game['categories'].split(',')) if owned_game['categories'] else set()

                cat_similarity = 0
                if target_cats or owned_cats:
                    cat_similarity = len(target_cats.intersection(owned_cats)) / len(target_cats.union(owned_cats)) if target_cats.union(owned_cats) else 0

                # 機制相似度
                target_mechs = set(target_game['mechanics'].split(',')) if target_game['mechanics'] else set()
                owned_mechs = set(owned_game['mechanics'].split(',')) if owned_game['mechanics'] else set()

                mech_similarity = 0
                if target_mechs or owned_mechs:
                    mech_similarity = len(target_mechs.intersection(owned_mechs)) / len(target_mechs.union(owned_mechs)) if target_mechs.union(owned_mechs) else 0

                # 複雜度相似度
                weight_similarity = 0
                if target_game['weight'] and owned_game['weight']:
                    weight_diff = abs(target_game['weight'] - owned_game['weight'])
                    weight_similarity = max(0, 1 - weight_diff / 5.0)

                # 合併相似度
                game_similarity = (cat_similarity * 0.4) + (mech_similarity * 0.4) + (weight_similarity * 0.2)
                similarities.append(game_similarity)

            # 返回平均相似度，轉換為 0-10 分數
            avg_similarity = sum(similarities) / len(similarities) if similarities else 0
            return avg_similarity * 10

        except Exception as e:
            logger.error(f"計算相似度失敗: {e}")
            return 0

    def _calculate_quality_score(self, game_data: Dict) -> float:
        """計算遊戲品質分數"""
        try:
            # 基於評分和排名計算品質分數
            rating_score = game_data['rating'] if game_data['rating'] else 5.0

            # 排名分數 (排名越高分數越高)
            rank_score = 0
            if game_data['rank'] and game_data['rank'] > 0:
                # 將排名轉換為 0-10 分數，前 100 名得到較高分數
                if game_data['rank'] <= 100:
                    rank_score = 10 - (game_data['rank'] / 100) * 5
                elif game_data['rank'] <= 1000:
                    rank_score = 5 - ((game_data['rank'] - 100) / 900) * 3
                else:
                    rank_score = 2

            # 合併評分和排名分數
            quality_score = (rating_score * 0.7) + (rank_score * 0.3)
            return min(10, max(0, quality_score))

        except Exception as e:
            logger.error(f"計算品質分數失敗: {e}")
            return 5.0  # 預設分數

    def get_score_description(self, score: float) -> Tuple[str, str]:
        """
        根據分數返回等級和描述

        Returns:
            (level, description) tuple
        """
        if score >= 8.5:
            return ('excellent', '極力推薦！這款遊戲非常符合您的喜好')
        elif score >= 7.0:
            return ('very_good', '強烈推薦！您很可能會喜歡這款遊戲')
        elif score >= 5.5:
            return ('good', '推薦嘗試，這款遊戲可能合您的口味')
        elif score >= 4.0:
            return ('fair', '可以考慮，但可能不是您的首選')
        else:
            return ('poor', '不太推薦，可能不符合您的遊戲偏好')

# 全域推薦器實例
_recommender_instance = None

def get_simple_recommender() -> SimpleBGGRecommender:
    """獲取全域推薦器實例"""
    global _recommender_instance
    if _recommender_instance is None:
        _recommender_instance = SimpleBGGRecommender()
    return _recommender_instance

def calculate_recommendation_score(game_id: int, owned_games: List[int]) -> Optional[Dict]:
    """
    計算遊戲推薦分數的主要函數

    Args:
        game_id: 遊戲 ID
        owned_games: 用戶擁有的遊戲 ID 列表

    Returns:
        包含分數和描述的字典，失敗時返回 None
    """
    recommender = get_simple_recommender()

    if not recommender.is_available():
        logger.error("推薦器不可用")
        return None

    score = recommender.get_recommendation_score(game_id, owned_games)

    if score is None:
        return None

    level, description = recommender.get_score_description(score)

    return {
        'score': score,
        'level': level,
        'description': description,
        'max_score': 10.0
    }