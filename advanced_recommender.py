#!/usr/bin/env python3
"""
進階桌遊推薦系統
支援多種推薦算法，不依賴 Turi Create
"""

import json
import logging
import os
import sqlite3
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.decomposition import NMF
from sklearn.neighbors import NearestNeighbors

logger = logging.getLogger(__name__)

class AdvancedBoardGameRecommender:
    """進階桌遊推薦系統，支援多種推薦算法"""
    
    def __init__(self, db_path='data/bgg_rag.db'):
        self.db_path = db_path
        self.games_df = None
        self.ratings_df = None
        self.user_item_matrix = None
        self.content_features = None
        self.models = {}
        
    def check_database_exists(self):
        """檢查資料庫檔案是否存在"""
        return os.path.exists(self.db_path)
    
    def check_tables_exist(self):
        """檢查所需的資料表是否存在"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 檢查 game_detail 表
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='game_detail'")
            game_detail_exists = cursor.fetchone() is not None
            
            # 檢查 collection 表
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='collection'")
            collection_exists = cursor.fetchone() is not None
            
            conn.close()
            return game_detail_exists and collection_exists
            
        except Exception as e:
            logger.error(f"檢查資料表時發生錯誤: {e}")
            return False
    
    def load_data(self):
        """從資料庫載入遊戲和評分資料"""
        try:
            # 檢查資料庫檔案
            if not self.check_database_exists():
                logger.error(f"資料庫檔案不存在: {self.db_path}")
                return False
            
            # 檢查資料表
            if not self.check_tables_exist():
                logger.error("必要的資料表 (game_detail, collection) 不存在")
                return False
                
            conn = sqlite3.connect(self.db_path)
            
            # 載入遊戲資料
            games_query = """
            SELECT objectid, name, year, rating, rank, weight, 
                   minplayers, maxplayers, categories, mechanics
            FROM game_detail 
            WHERE objectid IS NOT NULL AND name IS NOT NULL
            """
            self.games_df = pd.read_sql_query(games_query, conn)
            
            if len(self.games_df) == 0:
                logger.error("game_detail 表中沒有有效的遊戲資料")
                conn.close()
                return False
            
            # 載入評分資料
            ratings_query = """
            SELECT c.objectid as game_id, 
                   'user_' || c.objectid as user_id,
                   COALESCE(c.rating, 
                       CASE 
                           WHEN c.status LIKE '%Own%' THEN 7.0
                           WHEN c.status LIKE '%Want%' THEN 6.0
                           ELSE 5.0
                       END
                   ) as rating
            FROM collection c
            INNER JOIN game_detail g ON c.objectid = g.objectid
            WHERE c.objectid IS NOT NULL
            """
            self.ratings_df = pd.read_sql_query(ratings_query, conn)
            conn.close()
            
            if len(self.ratings_df) == 0:
                logger.warning("沒有評分資料，將僅使用基於內容的推薦")
            
            logger.info(f"載入了 {len(self.games_df)} 個遊戲和 {len(self.ratings_df)} 個評分")
            return True
            
        except Exception as e:
            logger.error(f"載入資料時發生錯誤: {e}")
            return False
    
    def prepare_user_item_matrix(self):
        """準備用戶-物品評分矩陣"""
        self.user_item_matrix = self.ratings_df.pivot_table(
            index='user_id', 
            columns='game_id', 
            values='rating', 
            fill_value=0
        )
        logger.info(f"用戶-物品矩陣大小: {self.user_item_matrix.shape}")
    
    def prepare_content_features(self):
        """準備內容特徵（類別、機制等）"""
        # 合併類別和機制作為內容特徵
        content_texts = []
        for _, game in self.games_df.iterrows():
            features = []
            if pd.notna(game['categories']):
                features.extend(game['categories'].split(','))
            if pd.notna(game['mechanics']):
                features.extend(game['mechanics'].split(','))
            content_texts.append(' '.join(features))
        
        # 使用 TF-IDF 向量化
        tfidf = TfidfVectorizer(max_features=500, stop_words='english')
        self.content_features = tfidf.fit_transform(content_texts)
        logger.info(f"內容特徵矩陣大小: {self.content_features.shape}")
    
    def train_popularity_recommender(self):
        """訓練基於熱門度的推薦器"""
        popularity_scores = self.games_df.copy()
        
        # 計算綜合熱門度分數
        popularity_scores['popularity_score'] = (
            popularity_scores['rating'].fillna(0) * 0.4 +
            (10000 - popularity_scores['rank'].fillna(10000)) / 1000 * 0.6
        )
        
        popularity_scores = popularity_scores.sort_values('popularity_score', ascending=False)
        self.models['popularity'] = popularity_scores
        logger.info("熱門度推薦器訓練完成")
    
    def train_collaborative_filtering(self, n_factors=20):
        """訓練協同過濾推薦器（使用矩陣分解）"""
        if self.user_item_matrix is None:
            self.prepare_user_item_matrix()
        
        # 使用 NMF 進行矩陣分解
        nmf = NMF(n_components=n_factors, random_state=42, max_iter=200)
        
        # 轉換為非負矩陣
        matrix = self.user_item_matrix.values
        matrix[matrix < 0] = 0
        
        user_factors = nmf.fit_transform(matrix)
        item_factors = nmf.components_
        
        self.models['collaborative_filtering'] = {
            'user_factors': user_factors,
            'item_factors': item_factors,
            'user_index': self.user_item_matrix.index,
            'item_index': self.user_item_matrix.columns
        }
        
        logger.info(f"協同過濾推薦器訓練完成 (factors: {n_factors})")
    
    def train_content_based(self):
        """訓練基於內容的推薦器"""
        if self.content_features is None:
            self.prepare_content_features()
        
        # 計算內容相似性矩陣
        content_similarity = cosine_similarity(self.content_features)
        
        self.models['content_based'] = {
            'similarity_matrix': content_similarity,
            'game_index': self.games_df['objectid'].tolist()
        }
        
        logger.info("基於內容的推薦器訓練完成")
    
    def train_item_similarity(self):
        """訓練基於物品相似性的推薦器"""
        if self.user_item_matrix is None:
            self.prepare_user_item_matrix()
        
        # 計算物品-物品相似性
        item_similarity = cosine_similarity(self.user_item_matrix.T)
        
        self.models['item_similarity'] = {
            'similarity_matrix': item_similarity,
            'item_index': self.user_item_matrix.columns.tolist()
        }
        
        logger.info("物品相似性推薦器訓練完成")
    
    def train_all_models(self):
        """訓練所有推薦模型"""
        logger.info("開始訓練所有推薦模型...")
        
        if not self.load_data():
            return False
        
        self.prepare_user_item_matrix()
        self.prepare_content_features()
        
        self.train_popularity_recommender()
        self.train_collaborative_filtering()
        self.train_content_based()
        self.train_item_similarity()
        
        logger.info("所有推薦模型訓練完成")
        return True
    
    def recommend_popularity(self, owned_games: List[int], num_recs: int = 10) -> List[Dict]:
        """基於熱門度的推薦"""
        if 'popularity' not in self.models:
            return []
        
        popularity_df = self.models['popularity']
        owned_set = set(owned_games)
        
        recommendations = []
        for _, game in popularity_df.iterrows():
            if game['objectid'] not in owned_set and len(recommendations) < num_recs:
                recommendations.append({
                    'game_id': game['objectid'],
                    'name': game['name'],
                    'year': game['year'],
                    'rating': round(game['rating'] or 0, 1),
                    'rank': game['rank'] or 0,
                    'weight': round(game['weight'] or 0, 1),
                    'rec_score': round(game['popularity_score'], 2),
                    'algorithm': 'popularity'
                })
        
        return recommendations
    
    def recommend_content_based(self, owned_games: List[int], num_recs: int = 10) -> List[Dict]:
        """基於內容的推薦"""
        if 'content_based' not in self.models:
            return []
        
        model = self.models['content_based']
        similarity_matrix = model['similarity_matrix']
        game_index = model['game_index']
        
        owned_set = set(owned_games)
        
        # 如果沒有擁有的遊戲，使用熱門度推薦作為後備
        if not owned_games:
            logger.info("沒有擁有的遊戲，使用熱門度推薦作為內容推薦的後備")
            return self.recommend_popularity([], num_recs)
        
        # 計算與擁有遊戲的平均相似度
        game_scores = {}
        for i, game_id in enumerate(game_index):
            if game_id in owned_set:
                continue
            
            # 計算與所有擁有遊戲的相似度
            similarities = []
            for owned_game in owned_games:
                if owned_game in game_index:
                    owned_idx = game_index.index(owned_game)
                    similarities.append(similarity_matrix[i][owned_idx])
            
            if similarities:
                game_scores[game_id] = np.mean(similarities)
        
        # 排序並取前N個
        sorted_games = sorted(game_scores.items(), key=lambda x: x[1], reverse=True)[:num_recs]
        
        recommendations = []
        for game_id, score in sorted_games:
            game_info = self.games_df[self.games_df['objectid'] == game_id].iloc[0]
            recommendations.append({
                'game_id': game_id,
                'name': game_info['name'],
                'year': game_info['year'],
                'rating': round(game_info['rating'] or 0, 1),
                'rank': game_info['rank'] or 0,
                'weight': round(game_info['weight'] or 0, 1),
                'rec_score': round(score, 2),
                'algorithm': 'content_based'
            })
        
        return recommendations
    
    def recommend_hybrid(self, owned_games: List[int], num_recs: int = 10, 
                        weights: Dict[str, float] = None) -> List[Dict]:
        """混合推薦算法"""
        if weights is None:
            weights = {
                'popularity': 0.5,  # 提高熱門度權重，適用於小數據集
                'content_based': 0.5,
                'collaborative_filtering': 0.0  # 暫時關閉協同過濾，因為數據太少
            }
        
        all_recommendations = {}
        successful_algorithms = 0
        
        # 獲取各種算法的推薦
        if 'popularity' in weights and weights['popularity'] > 0:
            pop_recs = self.recommend_popularity(owned_games, num_recs * 2)
            logger.info(f"熱門度推薦獲得 {len(pop_recs)} 個結果")
            if pop_recs:
                successful_algorithms += 1
                for rec in pop_recs:
                    game_id = rec['game_id']
                    if game_id not in all_recommendations:
                        all_recommendations[game_id] = rec.copy()
                        all_recommendations[game_id]['hybrid_score'] = 0
                    all_recommendations[game_id]['hybrid_score'] += rec['rec_score'] * weights['popularity']
        
        if 'content_based' in weights and weights['content_based'] > 0:
            content_recs = self.recommend_content_based(owned_games, num_recs * 2)
            logger.info(f"內容推薦獲得 {len(content_recs)} 個結果")
            if content_recs:
                successful_algorithms += 1
                for rec in content_recs:
                    game_id = rec['game_id']
                    if game_id not in all_recommendations:
                        all_recommendations[game_id] = rec.copy()
                        all_recommendations[game_id]['hybrid_score'] = 0
                    all_recommendations[game_id]['hybrid_score'] += rec['rec_score'] * weights['content_based']
        
        # 如果沒有任何推薦結果，直接返回熱門度推薦
        if not all_recommendations:
            logger.warning("混合推薦沒有結果，返回純熱門度推薦")
            return self.recommend_popularity(owned_games, num_recs)
        
        # 排序並返回前N個
        sorted_recs = sorted(all_recommendations.values(), 
                           key=lambda x: x['hybrid_score'], reverse=True)[:num_recs]
        
        for rec in sorted_recs:
            rec['algorithm'] = 'hybrid'
            rec['rec_score'] = round(rec['hybrid_score'], 2)
            del rec['hybrid_score']
        
        return sorted_recs
    
    def get_similar_games(self, game_id: int, num_similar: int = 5) -> List[Dict]:
        """獲取相似遊戲"""
        if 'content_based' not in self.models:
            return []
        
        model = self.models['content_based']
        similarity_matrix = model['similarity_matrix']
        game_index = model['game_index']
        
        if game_id not in game_index:
            return []
        
        game_idx = game_index.index(game_id)
        similarities = similarity_matrix[game_idx]
        
        # 獲取最相似的遊戲（排除自己）
        similar_indices = np.argsort(similarities)[::-1][1:num_similar+1]
        
        similar_games = []
        for idx in similar_indices:
            similar_game_id = game_index[idx]
            game_info = self.games_df[self.games_df['objectid'] == similar_game_id].iloc[0]
            similar_games.append({
                'game_id': similar_game_id,
                'name': game_info['name'],
                'year': game_info['year'],
                'rating': round(game_info['rating'] or 0, 1),
                'similarity_score': round(similarities[idx], 2),
                'algorithm': 'similarity'
            })
        
        return similar_games
    
    def save_models(self, model_dir: str):
        """保存訓練好的模型"""
        os.makedirs(model_dir, exist_ok=True)
        
        model_info = {
            'algorithms': list(self.models.keys()),
            'num_games': len(self.games_df),
            'num_ratings': len(self.ratings_df),
            'trained_at': pd.Timestamp.now().isoformat()
        }
        
        with open(os.path.join(model_dir, 'model_info.json'), 'w') as f:
            json.dump(model_info, f, indent=2)
        
        # 保存簡化的模型數據
        if 'popularity' in self.models:
            self.models['popularity'].to_json(
                os.path.join(model_dir, 'popularity_model.json'), 
                orient='records'
            )
        
        logger.info(f"模型已保存到 {model_dir}")

def main():
    """主函數 - CLI 介面"""
    import argparse
    
    parser = argparse.ArgumentParser(description="進階桌遊推薦系統")
    parser.add_argument('--train', action='store_true', help='訓練模型')
    parser.add_argument('--model-dir', default='data/advanced_models', help='模型目錄')
    parser.add_argument('--algorithm', choices=['popularity', 'content', 'hybrid'], 
                       default='hybrid', help='推薦算法')
    parser.add_argument('--num-recs', type=int, default=10, help='推薦數量')
    parser.add_argument('--owned-games', type=int, nargs='*', help='已擁有的遊戲ID')
    parser.add_argument('--similar-to', type=int, help='尋找相似遊戲的ID')
    parser.add_argument('--verbose', '-v', action='store_true', help='詳細輸出')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.basicConfig(level=logging.INFO)
    
    recommender = AdvancedBoardGameRecommender()
    
    if args.train:
        print("🎯 開始訓練進階推薦模型...")
        success = recommender.train_all_models()
        if success:
            recommender.save_models(args.model_dir)
            print(f"✅ 模型訓練完成並保存到 {args.model_dir}")
        else:
            print("❌ 模型訓練失敗")
        return
    
    # 載入資料進行推薦
    if not recommender.load_data():
        print("❌ 無法載入資料")
        return
    
    recommender.prepare_user_item_matrix()
    recommender.prepare_content_features()
    recommender.train_all_models()
    
    owned_games = args.owned_games or []
    
    if args.similar_to:
        print(f"🔍 尋找與遊戲 {args.similar_to} 相似的遊戲:")
        similar = recommender.get_similar_games(args.similar_to, args.num_recs)
        for game in similar:
            print(f"  {game['name']} ({game['year']}) - 相似度: {game['similarity_score']}")
    else:
        print(f"🎲 使用 {args.algorithm} 算法推薦遊戲:")
        
        if args.algorithm == 'popularity':
            recs = recommender.recommend_popularity(owned_games, args.num_recs)
        elif args.algorithm == 'content':
            recs = recommender.recommend_content_based(owned_games, args.num_recs)
        elif args.algorithm == 'hybrid':
            recs = recommender.recommend_hybrid(owned_games, args.num_recs)
        
        for i, game in enumerate(recs, 1):
            print(f"  {i}. {game['name']} ({game['year']}) - 評分: {game['rating']}, 推薦分數: {game['rec_score']}")

if __name__ == '__main__':
    main()