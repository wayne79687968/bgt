#!/usr/bin/env python3
"""
推薦服務：封裝 board-game-recommender 與路徑計算
"""

import os
import json
import logging

logger = logging.getLogger(__name__)


def get_user_rg_paths(username: str):
    """獲取用戶特定的 RG 文件路徑（僅依賴檔案系統，不讀 app 設定）。"""
    if not username:
        raise ValueError("username is required for get_user_rg_paths")

    possible_dirs = ['/app/data', 'data', '/tmp/data']
    base_dir = None

    for data_dir in possible_dirs:
        if os.path.exists(data_dir) and os.access(data_dir, os.W_OK):
            base_dir = data_dir
            logger.info(f"📁 使用資料目錄: {base_dir}")
            break

    if not base_dir:
        base_dir = 'data'
        os.makedirs(base_dir, exist_ok=True)
        logger.warning(f"⚠️ 沒有找到可用的資料目錄，使用預設: {base_dir}")

    user_dir = os.path.join(base_dir, 'rg_users', username)
    os.makedirs(user_dir, exist_ok=True)

    return {
        'user_dir': user_dir,
        'games_file': os.path.join(user_dir, 'bgg_GameItem.jl'),
        'ratings_file': os.path.join(user_dir, 'bgg_RatingItem.jl'),
        'model_dir': os.path.join(user_dir, 'rg_model'),
        'full_model': os.path.join(user_dir, 'rg_model', 'full.npz'),
        'light_model': os.path.join(user_dir, 'rg_model', 'light.npz'),
    }


def get_advanced_recommendations(username: str, owned_ids, algorithm: str = 'hybrid', limit: int = 10):
    """使用 board-game-recommender 進行推薦（與 app 路由解耦）。"""
    try:
        from board_game_recommender.recommend import BGGRecommender
        import turicreate as tc  # noqa: F401 - 模型載入需要
        import pandas as pd
    except Exception as e:
        logger.error(f"❌ 依賴缺失，無法載入推薦器: {e}")
        return _fallback_popularity_recommendations(username, owned_ids, limit)

    try:
        logger.info(f"🔍 開始 board-game-recommender 推薦 - 用戶: {username}, 擁有遊戲: {len(owned_ids) if owned_ids else 0}")
        paths = get_user_rg_paths(username)
        model_path = paths['model_dir']
        if not os.path.exists(model_path):
            logger.warning(f"⚠️ 模型不存在: {model_path}")
            return _fallback_popularity_recommendations(username, owned_ids, limit)

        logger.info(f"📂 載入模型: {model_path}")
        try:
            model_files = os.listdir(model_path) if os.path.exists(model_path) else []
            if 'recommender' in model_files:
                recommender = BGGRecommender.load(model_path, dir_model='recommender')
            else:
                recommender = BGGRecommender.load(model_path)
            logger.info("✅ 模型載入成功")
        except Exception as load_error:
            logger.error(f"❌ 模型載入失敗: {load_error}")
            return _fallback_popularity_recommendations(username, owned_ids, limit)

        user_variants = [username.lower(), username, f"user_{username.lower()}", f"user_{username}"]

        # 嘗試從 .jl 推斷實際用戶名
        try:
            ratings_file = paths['ratings_file']
            if os.path.exists(ratings_file):
                with open(ratings_file, 'r', encoding='utf-8') as f:
                    first_line = f.readline().strip()
                    if first_line:
                        rating_data = json.loads(first_line)
                        if 'bgg_user_name' in rating_data:
                            actual_username = rating_data['bgg_user_name']
                            if actual_username not in user_variants:
                                user_variants.insert(0, actual_username)
        except Exception as jl_error:
            logger.warning(f"⚠️ 檢查 .jl 檔案失敗: {jl_error}")

        recommendations_df = None
        for user_variant in user_variants:
            try:
                rec_df = recommender.recommend(users=[user_variant], num_games=limit, exclude_known=True)
                if len(rec_df) > 0:
                    # 排除已擁有
                    if owned_ids:
                        rec_pd = rec_df.to_dataframe()
                        rec_pd = rec_pd[~rec_pd['bgg_id'].isin(owned_ids)]
                        import turicreate as tc  # 轉回 SFrame
                        rec_df = tc.SFrame(rec_pd)
                    recommendations_df = rec_df
                    break
            except Exception as variant_error:
                logger.warning(f"⚠️ 用戶名格式 {user_variant} 失敗: {variant_error}")
                continue

        # 若第一輪為空，再放寬 exclude_known 嘗試一次
        if (recommendations_df is None or len(recommendations_df) == 0):
            for user_variant in user_variants:
                try:
                    rec_df = recommender.recommend(users=[user_variant], num_games=limit, exclude_known=False)
                    if len(rec_df) > 0:
                        if owned_ids:
                            rec_pd = rec_df.to_dataframe()
                            rec_pd = rec_pd[~rec_pd['bgg_id'].isin(owned_ids)]
                            import turicreate as tc
                            rec_df = tc.SFrame(rec_pd)
                        recommendations_df = rec_df
                        break
                except Exception as variant_error:
                    logger.warning(f"⚠️ 放寬 exclude_known 後用戶名格式 {user_variant} 仍失敗: {variant_error}")
                    continue

        if recommendations_df is None or len(recommendations_df) == 0:
            logger.error("❌ 無推薦結果，改用熱門度後備推薦")
            return _fallback_popularity_recommendations(username, owned_ids, limit)

        recommendations = []
        for row in recommendations_df:
            recommendations.append({
                'game_id': int(row['bgg_id']),
                'name': str(row['name']),
                'year': int(row.get('year', 0)),
                'rating': float(row.get('avg_rating', 0.0)),
                'rank': int(row.get('rank', 0)),
                'rec_score': float(row.get('score', 0.0)),
                'source': 'board_game_recommender',
            })

        logger.info(f"✅ 產生 {len(recommendations)} 個推薦")
        return recommendations

    except Exception as e:
        logger.error(f"❌ 推薦發生錯誤: {e}")
        return _fallback_popularity_recommendations(username, owned_ids, limit)


def _fallback_popularity_recommendations(username: str, owned_ids, limit: int):
    """當協同過濾推薦失敗時，使用 JSONL 的遊戲資料計算熱門度做後備推薦。

    規則：以貝葉斯平均結合 avg_rating 與 num_votes 作為排序指標，排除已擁有遊戲。
    """
    try:
        from typing import List
        import json
        import math
        import pandas as pd
    except Exception:
        # 最保守的退路：回傳空列表
        return []

    try:
        paths = get_user_rg_paths(username)
        games_file = paths['games_file']

        if not os.path.exists(games_file):
            logger.warning(f"⚠️ 後備推薦失敗：找不到遊戲檔 {games_file}")
            return []

        records: List[dict] = []
        with open(games_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    # 只保留必要欄位
                    records.append({
                        'bgg_id': int(rec.get('bgg_id', 0) or 0),
                        'name': rec.get('name') or '',
                        'year': int(rec.get('year', 0) or 0),
                        'avg_rating': float(rec.get('avg_rating', 0.0) or 0.0),
                        'num_votes': int(rec.get('num_votes', 0) or 0),
                        'rank': int(rec.get('rank', 0) or 0)
                    })
                except Exception:
                    continue

        if not records:
            logger.warning("⚠️ 後備推薦失敗：遊戲資料為空")
            return []

        df = pd.DataFrame(records)
        df = df[df['bgg_id'] > 0]
        original_df = df
        if owned_ids:
            df = df[~df['bgg_id'].isin(set(owned_ids))]
        if df.empty:
            # 若排除已擁有後沒有可推薦，放寬規則：允許包含已擁有的，至少提供一組人氣清單
            logger.warning("⚠️ 後備推薦：過濾後無遊戲可推薦，改為包含已擁有的熱門清單")
            df = original_df

        global_mean = df['avg_rating'].replace(0, pd.NA).dropna().mean()
        if not isinstance(global_mean, float) or math.isnan(global_mean):
            global_mean = 6.5
        m = 50  # 平衡參數
        df['rec_score'] = (df['num_votes'] * df['avg_rating'] + m * global_mean) / (df['num_votes'] + m).replace(0, m)

        top = df.sort_values(['rec_score', 'num_votes', 'avg_rating'], ascending=[False, False, False]).head(max(1, limit))
        recommendations = []
        for _, row in top.iterrows():
            recommendations.append({
                'game_id': int(row['bgg_id']),
                'name': str(row['name']),
                'year': int(row.get('year', 0) or 0),
                'rating': float(row.get('avg_rating', 0.0) or 0.0),
                'rank': int(row.get('rank', 0) or 0),
                'rec_score': float(row.get('rec_score', 0.0) or 0.0),
                'source': 'popularity_fallback',
            })
        logger.info(f"✅ 後備推薦產生 {len(recommendations)} 筆")
        return recommendations
    except Exception as e:
        logger.error(f"❌ 後備推薦發生錯誤: {e}")
        return []


