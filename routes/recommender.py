from flask import render_template, redirect, url_for, flash, session, request
from datetime import datetime
import os

from routes import recommender_bp
from email_auth import login_required
from database import get_db_connection
from services.recommender_service import get_user_rg_paths, get_advanced_recommendations


@recommender_bp.route('/recommendations')
@login_required
def recommendations():
    username = _get_bgg_username()
    if not username:
        flash('請先在設定頁設定 BGG 使用者名稱並同步收藏', 'info')
        return redirect(url_for('settings'))

    # 檢查模型是否存在
    user_paths = get_user_rg_paths(username)
    model_path = user_paths['model_dir']
    if not os.path.exists(model_path):
        flash('推薦模型尚未訓練，請先到設定頁點擊「🚀 一鍵重新訓練」。', 'warning')
        return redirect(url_for('settings'))

    owned_ids = _load_owned_object_ids()

    algorithm = request.args.get('algorithm', 'hybrid')
    recommendations = get_advanced_recommendations(username, owned_ids, algorithm=algorithm, limit=30)
    if not recommendations:
        flash('無法獲取推薦，請檢查模型是否正確訓練', 'error')
        return redirect(url_for('settings'))

    available_algorithms = [
        {'value': 'hybrid', 'name': '混合推薦 (Hybrid)', 'description': '結合多種算法的推薦'},
        {'value': 'popularity', 'name': '熱門推薦 (Popularity)', 'description': '基於遊戲熱門度的推薦'},
        {'value': 'content', 'name': '內容推薦 (Content-based)', 'description': '基於遊戲特徵相似性的推薦'}
    ]

    current_algorithm = algorithm
    current_view = request.args.get('view', 'search')

    return render_template('recommendations.html',
                           recommendations=recommendations,
                           bgg_username=username,
                           available_algorithms=available_algorithms,
                           current_algorithm=current_algorithm,
                           current_view=current_view,
                           last_updated=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))


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


