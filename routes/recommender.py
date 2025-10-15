from flask import render_template, redirect, url_for, flash, session, request, jsonify
from datetime import datetime
import os

from routes import recommender_bp
from email_auth import login_required
from database import get_db_connection
from services.recommender_service import get_user_rg_paths, get_advanced_recommendations
import threading
from datetime import datetime
import os
import json
import requests
from typing import Optional


@recommender_bp.route('/rg-recommender')
def rg_recommender():
    return redirect(url_for('recommender.recommendations'))


@recommender_bp.route('/recommendations', endpoint='recommendations')
@login_required
def recommendations():
    username = _get_bgg_username()
    if not username:
        flash('請先在設定頁設定 BGG 使用者名稱並同步收藏', 'info')
        return redirect(url_for('settings'))

    # 檢查模型是否存在（不存在時仍嘗試後備推薦，不再 302）
    user_paths = get_user_rg_paths(username)
    model_path = user_paths['model_dir']
    if not os.path.exists(model_path):
        flash('推薦模型尚未訓練：將先提供熱門度後備推薦。', 'warning')

    # 精簡：不主動產生清單，僅提供搜尋與單一遊戲打分
    owned_ids = _load_owned_object_ids()
    algorithm = request.args.get('algorithm', 'hybrid')
    recommendations = []

    available_algorithms = []

    current_algorithm = algorithm
    current_view = request.args.get('view', 'search')

    return render_template('recommendations.html',
                           recommendations=recommendations,
                           bgg_username=username,
                           available_algorithms=available_algorithms,
                           current_algorithm=current_algorithm,
                           current_view=current_view,
                           last_updated=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))


@recommender_bp.route('/api/bgg/search', methods=['POST'])
@login_required
def api_bgg_search():
    try:
        data = request.get_json()
        query = data.get('query', '').strip()
        # 可選的回傳數量上限（不指定則不限制）
        limit = None
        try:
            raw_limit = data.get('limit')
            if isinstance(raw_limit, (int, float)):
                limit = int(raw_limit)
            elif isinstance(raw_limit, str) and raw_limit.isdigit():
                limit = int(raw_limit)
            if limit is not None and limit <= 0:
                limit = None
        except Exception:
            limit = None
        if not query:
            return jsonify({'success': False, 'message': '搜尋關鍵字不能為空'})
        import xml.etree.ElementTree as ET
        import urllib.parse
        # 不使用 exact 參數，維持 BGG 預設模糊搜尋
        url = f"https://boardgamegeek.com/xmlapi2/search?{urllib.parse.urlencode({'query': query, 'type': 'boardgame'})}"
        import requests
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        root = ET.fromstring(response.text)
        results = []
        items = root.findall('item')
        # 逐步累積，若有指定 limit 則提早停止
        for item in items:
            game_id = item.get('id')
            name_element = item.find('name')
            year_element = item.find('yearpublished')
            if game_id and name_element is not None:
                results.append({'id': game_id, 'name': name_element.get('value', ''), 'year': year_element.get('value') if year_element is not None else None})
            if limit is not None and len(results) >= limit:
                break
        return jsonify({'success': True, 'results': results, 'query': query})
    except Exception as e:
        return jsonify({'success': False, 'message': f'搜尋失敗: {str(e)}'})


def _get_bgg_username():
    # 從 app 設定的 app_settings 取值
    from app import get_app_setting  # 延遲引入以避免循環
    return get_app_setting('bgg_username', '')


def _load_owned_object_ids():
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT objectid FROM collection")
            return [row[0] for row in cursor.fetchall()]
    except Exception:
        return []


# 一鍵重新訓練狀態（與前端輪詢介面相容）
bgg_training_status = {
    'is_running': False,
    'current_step': '待機',
    'progress': 0,
    'message': '',
    'started_at': None,
    'ended_at': None,
    'completed': False,
    'error': False,
    'error_message': ''
}

def _set_training_status(**kwargs):
    for k, v in kwargs.items():
        bgg_training_status[k] = v
    # 自動補充時間戳
    if 'is_running' in kwargs and kwargs['is_running'] and not bgg_training_status.get('started_at'):
        bgg_training_status['started_at'] = datetime.now()
    if 'completed' in kwargs and kwargs['completed']:
        bgg_training_status['ended_at'] = datetime.now()


@recommender_bp.route('/api/bgg/retrain-full', methods=['POST'])
@login_required
def api_bgg_retrain_full():
    if bgg_training_status.get('is_running'):
        return jsonify({'success': False, 'message': '訓練已在進行中'}), 400

    username = _get_bgg_username()
    if not username:
        return jsonify({'success': False, 'message': '請先設定 BGG 用戶名'}), 400

    _set_training_status(is_running=True, current_step='初始化', progress=0, message='準備環境', completed=False, error=False, error_message='')

    def _task():
        try:
            # 第一步：抓取 BGG 收藏與評分
            _set_training_status(current_step='抓取資料', progress=10, message=f'抓取 {username} 的 BGG 收藏...')
            try:
                from bgg_scraper_extractor import BGGScraperExtractor
                ex = BGGScraperExtractor()
                ok = ex.export_to_jsonl(username)
                if not ok:
                    _set_training_status(is_running=False, error=True, error_message='抓取收藏失敗', message='抓取收藏失敗')
                    return
            except Exception as e:
                _set_training_status(is_running=False, error=True, error_message=f'抓取收藏異常: {e}', message='抓取收藏異常')
                return

            _set_training_status(current_step='準備訓練資料', progress=30, message='檢查訓練資料')
            from services.recommender_service import get_user_rg_paths
            paths = get_user_rg_paths(username)
            games_file = paths['games_file']
            ratings_file = paths['ratings_file']
            model_dir = paths['model_dir']

            if not (os.path.exists(games_file) and os.path.exists(ratings_file)):
                _set_training_status(is_running=False, error=True, error_message='訓練資料不存在', message='訓練資料不存在')
                return

            # 第二步：訓練模型
            _set_training_status(current_step='訓練模型', progress=60, message='使用 board-game-recommender 訓練')
            try:
                from board_game_recommender.recommend import BGGRecommender
                import turicreate as tc  # noqa: F401
                import shutil
                os.makedirs(model_dir, exist_ok=True)
                rec = BGGRecommender.train_from_files(games_file=games_file, ratings_file=ratings_file)
                # 先清理舊資料（避免混合新舊檔案）
                for sub in ('recommender', 'similarity', 'games', 'ratings', 'clusters', 'compilations'):
                    p = os.path.join(model_dir, sub)
                    if os.path.exists(p):
                        try:
                            shutil.rmtree(p)
                        except Exception:
                            pass
                rec.save(model_dir)
            except Exception as e:
                _set_training_status(is_running=False, error=True, error_message=f'訓練失敗: {e}', message='訓練失敗')
                return

            # 完成
            _set_training_status(current_step='完成', progress=100, message='訓練完成', is_running=False, completed=True)
        except Exception as e:
            _set_training_status(is_running=False, error=True, error_message=str(e), message='發生未知錯誤')

    t = threading.Thread(target=_task, daemon=True)
    t.start()

    return jsonify({'success': True, 'message': 'BGG 一鍵訓練已啟動'})


@recommender_bp.route('/api/bgg/training-status', methods=['GET'])
@login_required
def api_bgg_training_status():
    st = bgg_training_status.copy()
    if st.get('started_at'):
        st['started_at'] = st['started_at'].isoformat()
    if st.get('ended_at'):
        st['ended_at'] = st['ended_at'].isoformat()
    return jsonify({'success': True, 'status': st})


@recommender_bp.route('/api/bgg/training-reset', methods=['POST'])
@login_required
def api_bgg_training_reset():
    # 強制重置訓練狀態（用於異常卡住時）
    bgg_training_status.update({
        'is_running': False,
        'current_step': '待機',
        'progress': 0,
        'message': '已重置',
        'started_at': None,
        'ended_at': None,
        'completed': False,
        'error': False,
        'error_message': ''
    })
    return jsonify({'success': True, 'message': '訓練狀態已重置'})

# 簡化的 RG 抓取任務狀態（維持原有接口語意）
rg_task_status = {'is_running': False, 'start_time': None, 'progress': 0, 'message': '', 'stdout_tail': [], 'stderr_tail': [], 'last_update': None}

def update_rg_task_status(progress: Optional[int] = None, message: Optional[str] = None, stdout_line: Optional[str] = None, stderr_line: Optional[str] = None):
    if progress is not None:
        rg_task_status['progress'] = progress
    if message is not None:
        rg_task_status['message'] = message
    if stdout_line:
        rg_task_status['stdout_tail'] = (rg_task_status.get('stdout_tail', []) + [stdout_line])[-50:]
    if stderr_line:
        rg_task_status['stderr_tail'] = (rg_task_status.get('stderr_tail', []) + [stderr_line])[-50:]
    rg_task_status['last_update'] = datetime.now()
@recommender_bp.route('/api/rg-status', methods=['GET'])
@login_required
def api_rg_status():
    username = _get_bgg_username()
    if not username:
        return jsonify({'success': False, 'message': '請先設定 BGG 用戶名', 'need_username': True})
    user_paths = get_user_rg_paths(username)
    model_dir_exists = os.path.exists(user_paths['model_dir'])
    games_file_exists = os.path.exists(user_paths['games_file'])
    ratings_file_exists = os.path.exists(user_paths['ratings_file'])
    data_completeness = (40 if games_file_exists else 0) + (30 if ratings_file_exists else 0) + (30 if model_dir_exists else 0)
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
    }
    return jsonify({'success': True, 'status': status})
@recommender_bp.route('/api/rg-scrape', methods=['POST'])
@login_required
def api_rg_scrape():
    if rg_task_status.get('is_running'):
        return jsonify({'success': False, 'message': '已有抓取任務在進行中'}), 400
    username = _get_bgg_username()
    if not username:
        return jsonify({'success': False, 'message': '請先在設定頁面輸入 BGG 用戶名'}), 400
    rg_task_status.update({'is_running': True, 'start_time': datetime.now(), 'progress': 0, 'message': '啟動中', 'stdout_tail': [], 'stderr_tail': []})
    def _run():
        try:
            from bgg_scraper_extractor import BGGScraperExtractor
            update_rg_task_status(10, f'開始抓取 {username} 收藏...')
            ex = BGGScraperExtractor()
            ok = ex.export_to_jsonl(username)
            if ok:
                update_rg_task_status(100, f'成功抓取 {username} 的 BGG 資料')
            else:
                update_rg_task_status(0, f'抓取失敗')
        except Exception as e:
            update_rg_task_status(0, f'抓取異常: {e}')
        finally:
            rg_task_status['is_running'] = False
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify({'success': True, 'message': '抓取任務已啟動'})


@recommender_bp.route('/api/rg-task-status', methods=['GET'])
@login_required
def api_rg_task_status_endpoint():
    st = rg_task_status.copy()
    st['elapsed_seconds'] = int((datetime.now() - st['start_time']).total_seconds()) if st.get('start_time') else 0
    st['stdout_tail'] = st.get('stdout_tail', [])[-20:]
    st['stderr_tail'] = st.get('stderr_tail', [])[-20:]
    if st.get('last_update'):
        st['last_update'] = st['last_update'].isoformat()
    return jsonify({'success': True, 'status': st})


@recommender_bp.route('/api/rg/model-status', methods=['GET'])
@login_required
def api_rg_model_status():
    try:
        username = _get_bgg_username()
        if not username:
            return jsonify({'success': False, 'message': '請先設定 BGG 使用者名稱'})
        user_paths = get_user_rg_paths(username)
        has_games_data = os.path.exists(user_paths['games_file'])
        has_ratings_data = os.path.exists(user_paths['ratings_file'])
        has_full_model = os.path.exists(user_paths['full_model'])
        has_light_model = os.path.exists(user_paths['light_model'])
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
            from board_game_recommender.recommend import BGGRecommender as BRec
            fallback_available = True
        except ImportError:
            pass
        games_count = 0
        ratings_count = 0
        if has_games_data:
            try:
                with open(user_paths['games_file'], 'r', encoding='utf-8') as f:
                    games_count = sum(1 for _ in f)
            except Exception:
                pass
        if has_ratings_data:
            try:
                with open(user_paths['ratings_file'], 'r', encoding='utf-8') as f:
                    ratings_count = sum(1 for _ in f)
            except Exception:
                pass
        can_use_full = bgg_recommender_available and has_games_data and has_ratings_data
        can_use_light = light_recommender_available and has_games_data and has_light_model
        can_use_fallback = fallback_available
        return jsonify({'success': True, 'result': {
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
                'fallback_recommender': can_use_fallback
            },
            'availability': {
                'full_recommender': can_use_full,
                'light_recommender': can_use_light,
                'fallback_recommender': can_use_fallback
            }
        }})
    except Exception as e:
        return jsonify({'success': False, 'message': f'處理請求時發生錯誤: {str(e)}'})


@recommender_bp.route('/api/rg/recommend-score', methods=['POST'])
@login_required
def api_rg_recommend_score():
    try:
        data = request.get_json()
        game_id = data.get('game_id')
        game_name = data.get('game_name', 'Unknown Game')
        if not game_id:
            return jsonify({'success': False, 'message': '遊戲 ID 不能為空'})
        username = _get_bgg_username()
        owned_ids = _load_owned_object_ids()
        if not owned_ids:
            return jsonify({'success': False, 'message': '請先同步您的 BGG 收藏才能計算推薦分數'})
        from board_game_recommender.recommend import BGGRecommender
        user_paths = get_user_rg_paths(username)
        model_path = user_paths['model_dir']
        if not os.path.exists(model_path):
            return jsonify({'success': False, 'message': '尚未訓練推薦模型。請先到設定頁點擊「🚀 一鍵重新訓練」。'})
        recommender = BGGRecommender.load(model_path)
        rec_df = recommender.recommend(users=[username.lower()], num_games=1000, exclude_known=False)
        rec_pd = rec_df.to_dataframe()
        target = rec_pd[rec_pd['bgg_id'] == int(game_id)]
        if len(target) == 0:
            return jsonify({'success': False, 'message': '此遊戲未在推薦列表中。'})
        raw_score = float(target['score'].iloc[0])
        score = raw_score * 10 if raw_score <= 1.0 else (raw_score * 2 if raw_score <= 5.0 else min(raw_score, 10))
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
        return jsonify({'success': True, 'result': {'game_id': game_id, 'name': game_name, 'score': score, 'max_score': 10.0, 'score_level': level, 'score_description': description, 'details': f'基於您的 {len(owned_ids)} 個收藏遊戲使用預訓練模型計算'}})
    except Exception as e:
        return jsonify({'success': False, 'message': f'處理請求時發生錯誤: {str(e)}'})


