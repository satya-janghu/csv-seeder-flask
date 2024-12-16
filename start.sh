#!/bin/bash

# Create and activate virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

# Initialize database
python init_db.py

# Start Redis if not running
if ! pgrep redis-server > /dev/null; then
    redis-server &
    echo "Started Redis server"
fi

# Start Celery worker
celery -A celery_app.celery worker --loglevel=INFO &
echo "Started Celery worker"

# Start Flask application with Gunicorn
gunicorn --workers=4 --bind=0.0.0.0:5000 run:app

# Note: Use Ctrl+C to stop all processes 