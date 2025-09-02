#!/usr/bin/env python3
"""
遊戲推薦服務
結合本地推薦系統和 Recommend.Games 功能
支援用戶選擇遊戲後獲得推薦分數
"""

import json
import logging
import requests
from typing import Dict, List, Optional, Tuple
import numpy as np
from datetime import datetime
from database import get_db_connection

logger = logging.getLogger(__name__)

class GameRecommendationService:
    """遊戲推薦服務，整合多種推薦方式"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'BGG-RAG-Daily/1.0'
        })
    
    def get_game_recommendations_by_selection(self, selected_games: List[int], 
                                             num_recommendations: int = 10) -> Dict:
        """
        根據用戶選擇的遊戲獲得推薦分數
        
        Args:
            selected_games: 用戶選擇的遊戲 ID 列表
            num_recommendations: 推薦數量
        
        Returns:
            Dict: 包含推薦結果和分數的字典
        """
        try:
            # 1. 使用本地推薦系統
            local_recommendations = self._get_local_recommendations(selected_games, num_recommendations)
            
            # 2. 嘗試使用 Recommend.Games 風格的相似性計算
            similarity_recommendations = self._get_similarity_recommendations(selected_games, num_recommendations)
            
            # 3. 結合多種推薦結果
            combined_recommendations = self._combine_recommendations(
                local_recommendations, similarity_recommendations
            )
            
            return {
                'success': True,
                'selected_games': selected_games,
                'recommendations': combined_recommendations,
                'metadata': {
                    'timestamp': datetime.now().isoformat(),
                    'total_recommendations': len(combined_recommendations),
                    'methods_used': ['local', 'similarity'],
                    'confidence_threshold': 0.5
                }
            }
            
        except Exception as e:
            logger.error(f"獲取遊戲推薦失敗: {e}")
            return {
                'success': False,
                'error': str(e),
                'selected_games': selected_games,
                'recommendations': []
            }
    
    def _get_local_recommendations(self, selected_games: List[int], num_recs: int) -> List[Dict]:
        """使用本地推薦系統獲得推薦"""
        try:
            from advanced_recommender import AdvancedBoardGameRecommender
            
            recommender = AdvancedBoardGameRecommender()
            
            # 檢查系統狀態
            if not recommender.check_database_connection():
                logger.warning("本地推薦系統資料庫連接失敗")
                return []
            
            if not recommender.check_tables_exist():
                logger.warning("本地推薦系統缺少必要資料表")
                return []
            
            # 載入數據並訓練
            if not recommender.load_data():
                logger.warning("本地推薦系統資料載入失敗")
                return []
            
            recommender.train_all_models()
            
            # 獲取推薦
            recommendations = recommender.recommend_hybrid(selected_games, num_recs)
            
            # 添加推薦來源和置信度
            for rec in recommendations:
                rec['source'] = 'local'
                rec['method'] = 'hybrid'
                # 基於分數計算置信度
                rec['confidence'] = min(rec.get('score', 0) / 10.0, 1.0)
            
            return recommendations
            
        except Exception as e:
            logger.error(f"本地推薦系統錯誤: {e}")
            return []
    
    def _get_similarity_recommendations(self, selected_games: List[int], num_recs: int) -> List[Dict]:
        """基於遊戲相似性的推薦（參考 Recommend.Games 方法）"""
        try:
            recommendations = []
            
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # 獲取選中遊戲的詳細資料
                selected_games_data = {}
                for game_id in selected_games:
                    cursor.execute("""
                        SELECT objectid, name, categories, mechanics, designers, 
                               rating, weight, minplayers, maxplayers
                        FROM game_detail 
                        WHERE objectid = %s
                    """, (game_id,))
                    result = cursor.fetchone()
                    
                    if result:
                        selected_games_data[game_id] = {
                            'objectid': result[0],
                            'name': result[1],
                            'categories': result[2] or '',
                            'mechanics': result[3] or '',
                            'designers': result[4] or '',
                            'rating': result[5] or 0,
                            'weight': result[6] or 0,
                            'minplayers': result[7] or 1,
                            'maxplayers': result[8] or 1
                        }
                
                if not selected_games_data:
                    return []
                
                # 獲取候選推薦遊戲
                cursor.execute("""
                    SELECT objectid, name, categories, mechanics, designers,
                           rating, weight, minplayers, maxplayers, rank
                    FROM game_detail 
                    WHERE objectid NOT IN %s 
                        AND rating IS NOT NULL 
                        AND rating > 6.0
                    ORDER BY rating DESC, rank ASC
                    LIMIT %s
                """, (tuple(selected_games), num_recs * 3))  # 獲取更多候選
                
                candidates = cursor.fetchall()
                
                # 計算相似性分數
                for candidate in candidates:
                    candidate_data = {
                        'objectid': candidate[0],
                        'name': candidate[1],
                        'categories': candidate[2] or '',
                        'mechanics': candidate[3] or '',
                        'designers': candidate[4] or '',
                        'rating': candidate[5] or 0,
                        'weight': candidate[6] or 0,
                        'minplayers': candidate[7] or 1,
                        'maxplayers': candidate[8] or 1,
                        'rank': candidate[9] or 10000
                    }
                    
                    # 計算與所選遊戲的平均相似度
                    similarity_scores = []
                    for selected_id, selected_data in selected_games_data.items():
                        similarity = self._calculate_game_similarity(selected_data, candidate_data)
                        similarity_scores.append(similarity)
                    
                    avg_similarity = np.mean(similarity_scores) if similarity_scores else 0
                    
                    # 結合相似性和質量分數
                    quality_score = (candidate_data['rating'] / 10.0) * 0.6 + \
                                   ((10000 - candidate_data['rank']) / 10000) * 0.4
                    
                    final_score = avg_similarity * 0.7 + quality_score * 0.3
                    
                    if final_score > 0.3:  # 最低相似度閾值
                        recommendations.append({
                            'objectid': candidate_data['objectid'],
                            'name': candidate_data['name'],
                            'rating': candidate_data['rating'],
                            'rank': candidate_data['rank'],
                            'score': round(final_score * 10, 2),
                            'similarity': round(avg_similarity, 3),
                            'confidence': min(final_score, 1.0),
                            'source': 'similarity',
                            'method': 'content_similarity'
                        })
                
                # 按分數排序並返回前 N 個
                recommendations.sort(key=lambda x: x['score'], reverse=True)
                return recommendations[:num_recs]
                
        except Exception as e:
            logger.error(f"相似性推薦計算失敗: {e}")
            return []
    
    def _calculate_game_similarity(self, game1: Dict, game2: Dict) -> float:
        """計算兩個遊戲之間的相似性（參考 Recommend.Games 方法）"""
        try:
            similarity_score = 0.0
            
            # 1. 類別相似性
            cats1 = set(game1['categories'].split(',')) if game1['categories'] else set()
            cats2 = set(game2['categories'].split(',')) if game2['categories'] else set()
            if cats1 or cats2:
                cat_similarity = len(cats1.intersection(cats2)) / len(cats1.union(cats2)) if cats1.union(cats2) else 0
                similarity_score += cat_similarity * 0.3
            
            # 2. 機制相似性
            mech1 = set(game1['mechanics'].split(',')) if game1['mechanics'] else set()
            mech2 = set(game2['mechanics'].split(',')) if game2['mechanics'] else set()
            if mech1 or mech2:
                mech_similarity = len(mech1.intersection(mech2)) / len(mech1.union(mech2)) if mech1.union(mech2) else 0
                similarity_score += mech_similarity * 0.4
            
            # 3. 設計師相似性
            des1 = set(game1['designers'].split(',')) if game1['designers'] else set()
            des2 = set(game2['designers'].split(',')) if game2['designers'] else set()
            if des1 or des2:
                des_similarity = len(des1.intersection(des2)) / len(des1.union(des2)) if des1.union(des2) else 0
                similarity_score += des_similarity * 0.1
            
            # 4. 數值特徵相似性
            # 複雜度相似性
            if game1['weight'] and game2['weight']:
                weight_diff = abs(game1['weight'] - game2['weight'])
                weight_similarity = max(0, 1 - weight_diff / 5.0)  # 5 是最大複雜度差異
                similarity_score += weight_similarity * 0.1
            
            # 玩家人數範圍相似性
            overlap_start = max(game1['minplayers'], game2['minplayers'])
            overlap_end = min(game1['maxplayers'], game2['maxplayers'])
            if overlap_start <= overlap_end:
                player_similarity = 1.0
            else:
                player_similarity = 0.5  # 部分重疊
            similarity_score += player_similarity * 0.1
            
            return min(similarity_score, 1.0)
            
        except Exception as e:
            logger.error(f"計算遊戲相似性失敗: {e}")
            return 0.0
    
    def _combine_recommendations(self, local_recs: List[Dict], similarity_recs: List[Dict]) -> List[Dict]:
        """結合多種推薦結果"""
        combined = {}
        
        # 添加本地推薦
        for rec in local_recs:
            game_id = rec['objectid']
            combined[game_id] = rec.copy()
            combined[game_id]['sources'] = ['local']
        
        # 添加或更新相似性推薦
        for rec in similarity_recs:
            game_id = rec['objectid']
            if game_id in combined:
                # 結合分數
                combined[game_id]['score'] = (combined[game_id]['score'] + rec['score']) / 2
                combined[game_id]['confidence'] = max(combined[game_id]['confidence'], rec['confidence'])
                combined[game_id]['sources'].append('similarity')
            else:
                rec['sources'] = ['similarity']
                combined[game_id] = rec
        
        # 轉換回列表並排序
        result = list(combined.values())
        result.sort(key=lambda x: x['score'], reverse=True)
        
        return result
    
    def get_game_details_for_selection(self, game_ids: List[int]) -> List[Dict]:
        """獲取遊戲詳細資料，用於選擇界面"""
        try:
            games = []
            
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                for game_id in game_ids:
                    cursor.execute("""
                        SELECT objectid, name, year, rating, rank, image, 
                               categories, mechanics, minplayers, maxplayers, 
                               minplaytime, maxplaytime
                        FROM game_detail 
                        WHERE objectid = %s
                    """, (game_id,))
                    result = cursor.fetchone()
                    
                    if result:
                        games.append({
                            'objectid': result[0],
                            'name': result[1],
                            'year': result[2],
                            'rating': result[3],
                            'rank': result[4],
                            'image': result[5],
                            'categories': result[6],
                            'mechanics': result[7],
                            'players': f"{result[8]}-{result[9]}人" if result[8] and result[9] else "未知",
                            'playtime': f"{result[10]}-{result[11]}分鐘" if result[10] and result[11] else "未知"
                        })
            
            return games
            
        except Exception as e:
            logger.error(f"獲取遊戲詳細資料失敗: {e}")
            return []

# 使用範例
if __name__ == "__main__":
    service = GameRecommendationService()
    
    # 用戶選擇幾款遊戲
    selected_games = [174430, 167791, 70323]  # 例如：Gloomhaven, Terraforming Mars, King of Tokyo
    
    # 獲取推薦
    result = service.get_game_recommendations_by_selection(selected_games, 5)
    
    if result['success']:
        print(f"根據您選擇的 {len(result['selected_games'])} 款遊戲，推薦以下遊戲：")
        for i, rec in enumerate(result['recommendations'], 1):
            print(f"{i}. {rec['name']} (分數: {rec['score']}, 置信度: {rec['confidence']:.2f})")
    else:
        print(f"推薦失敗: {result['error']}")