from flask import render_template, jsonify, request, session
from datetime import datetime
import os

from routes import admin_bp
from email_auth import full_access_required
from database import get_db_connection


@admin_bp.route('/creator-tracker')
@full_access_required
def creator_tracker():
    user = session.get('user', {})
    user_email = user.get('email', '')
    return render_template('creator_tracker.html', user_email=user_email)


@admin_bp.route('/api/creators/search', methods=['POST'])
@full_access_required
def api_search_creators():
    try:
        data = request.get_json()
        query = data.get('query', '').strip()
        creator_type = data.get('type', 'boardgamedesigner')
        if not query:
            return jsonify({'success': False, 'message': '請輸入搜尋關鍵字'})
        from creator_tracker import CreatorTracker
        tracker = CreatorTracker()
        results = tracker.search_creators(query, creator_type)
        return jsonify({'success': True, 'results': results})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@admin_bp.route('/creator/<int:creator_id>/<creator_type>')
def creator_details_page(creator_id, creator_type):
    return render_template('creator_details.html', creator_id=creator_id, creator_type=creator_type)


@admin_bp.route('/api/creators/<int:creator_id>/<creator_type>')
def api_get_creator_details(creator_id, creator_type):
    try:
        from creator_tracker import CreatorTracker
        tracker = CreatorTracker()
        details = tracker.get_creator_details(creator_id, creator_type)
        if not details:
            return jsonify({'success': False, 'message': '無法獲取詳細資料'})
        api_type = 'boardgamedesigner' if creator_type in ['designer', 'boardgamedesigner'] else 'boardgameartist'
        slug = details.get('slug')
        top_game = None
        if slug:
            top_games = tracker.get_all_creator_games(creator_id, slug, api_type, sort='average', limit=1)
            if top_games:
                game = top_games[0]
                top_game = {'name': game.get('name'), 'url': f"https://boardgamegeek.com/boardgame/{game.get('bgg_id')}"}
        recent_games = []
        if slug:
            games = tracker.get_all_creator_games(creator_id, slug, api_type, sort='yearpublished', limit=5)
            for game in games:
                recent_games.append({'name': game.get('name'), 'year': game.get('year'), 'url': f"https://boardgamegeek.com/boardgame/{game.get('bgg_id')}"})
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
        return jsonify({'success': True, 'creator': details})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@admin_bp.route('/api/creators/follow', methods=['POST'])
@full_access_required
def api_follow_creator():
    try:
        user_data = session.get('user', {})
        user_id = user_data.get('id')
        user_email = user_data.get('email')
        if not user_id:
            return jsonify({'success': False, 'message': '請先登入'})
        data = request.get_json()
        creator_bgg_id = data.get('creator_id')
        creator_type = data.get('type')
        action = data.get('action')
        if not all([creator_bgg_id, creator_type, action]):
            return jsonify({'success': False, 'message': '參數不完整'})
        if action == 'follow' and not user_email:
            return jsonify({'success': False, 'message': '請先在設定頁面設定 Email 地址才能使用追蹤功能'})
        from creator_tracker import CreatorTracker
        tracker = CreatorTracker()
        if action == 'follow':
            bgg_type_map = {'designer': 'boardgamedesigner', 'artist': 'boardgameartist'}
            bgg_type = bgg_type_map.get(creator_type, 'boardgamedesigner')
            details = tracker.get_creator_details(creator_bgg_id, bgg_type)
            if not details:
                return jsonify({'success': False, 'message': '無法獲取設計師資料'})
            creator_name = details['name']
            result = tracker.follow_creator(user_id, int(creator_bgg_id), bgg_type, creator_name)
            return jsonify(result)
        else:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    DELETE FROM user_follows
                    WHERE user_id = %s AND creator_id = (
                        SELECT id FROM creators WHERE bgg_id = %s
                    )
                """, (user_id, creator_bgg_id))
                conn.commit()
            return jsonify({'success': True, 'message': '已取消追蹤'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@admin_bp.route('/api/creators/following')
@full_access_required
def api_get_following_creators():
    try:
        user = session.get('user', {})
        user_id = user.get('id')
        if not user_id:
            return jsonify({'success': False, 'message': '請先登入'})
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT c.bgg_id, c.name, c.type, c.description, c.image_url, uf.followed_at
                FROM creators c
                JOIN user_follows uf ON c.id = uf.creator_id
                WHERE uf.user_id = %s
                ORDER BY uf.followed_at DESC
            """, (user_id,))
            creators = []
            for row in cursor.fetchall():
                creators.append({'bgg_id': row[0], 'name': row[1], 'type': row[2], 'description': row[3], 'image_url': row[4], 'followed_at': row[5]})
        return jsonify({'success': True, 'creators': creators})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@admin_bp.route('/api/cron-update-creators', methods=['POST'])
def cron_update_creators():
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
        import subprocess
        import threading
        def run_update():
            try:
                cmd = ['python3', 'update_creators.py']
                if force_update:
                    cmd.append('--force')
                subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
            except Exception:
                pass
        update_thread = threading.Thread(target=run_update)
        update_thread.daemon = True
        update_thread.start()
        return jsonify({'success': True, 'message': '設計師/繪師作品更新已開始', 'force': force_update, 'timestamp': datetime.now().isoformat()})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


