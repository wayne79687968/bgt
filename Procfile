web: gunicorn --bind 0.0.0.0:$PORT --timeout 120 --workers 1 --max-requests 1000 --worker-class sync start_simple:app
worker: python scheduler.py