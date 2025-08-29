web: gunicorn --bind 0.0.0.0:$PORT --timeout 300 --workers 1 --max-requests 1000 --preload start_simple:app
worker: python scheduler.py