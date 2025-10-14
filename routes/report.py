from flask import render_template, jsonify, request, session
from datetime import datetime
import os

from routes import report_bp
from email_auth import login_required
from database import get_db_connection, get_database_config


@report_bp.route('/bgg_times')
@login_required
def bgg_times():
    # 從原 app 導入幫手函數（延遲導入避免循環）
    from app import get_report_by_date, get_latest_report, parse_game_data_from_report, get_available_dates

    selected_date = request.args.get('date') or datetime.now().strftime('%Y-%m-%d')

    content, filename = get_report_by_date(selected_date)
    if content is None:
        content, filename = get_latest_report()
    if content is None:
        return render_template('error.html', error=filename)

    all_games = parse_game_data_from_report(content)
    current_page_games = all_games
    total_games = len(all_games)
    available_dates = get_available_dates()

    return render_template('bgg_times.html',
                         current_page_games=current_page_games,
                         filename=filename,
                         selected_date=selected_date,
                         available_dates=available_dates,
                         total_games=total_games,
                         last_updated=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))


@report_bp.route('/api/check-files', methods=['GET'])
@login_required
def api_check_files():
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
        return jsonify({'success': True, 'directory': report_dir, 'files': files_info, 'total_files': len(files_info)})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@report_bp.route('/api/check-database', methods=['GET'])
@login_required
def api_check_database():
    try:
        config = get_database_config()
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
            cursor.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name
            """)
            existing_tables = [row[0] for row in cursor.fetchall()]

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
                except Exception:
                    pass

            if 'forum_threads' in existing_tables:
                try:
                    cursor.execute("SELECT COUNT(*) as total_threads FROM forum_threads")
                    forum_threads_count = cursor.fetchone()[0]
                except Exception:
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


