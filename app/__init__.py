from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from celery import Celery
import os
import sys

# Add the parent directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import Config

db = SQLAlchemy()

# Initialize Celery with Redis broker
celery = Celery(
    'tasks',
    broker='redis://localhost:6379/0',
    backend='redis://localhost:6379/0',
    include=['app.tasks']
)

class ContextTask(celery.Task):
    def __call__(self, *args, **kwargs):
        from app import create_app
        with create_app().app_context():
            return self.run(*args, **kwargs)

celery.Task = ContextTask

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # Initialize extensions
    CORS(app, resources={r"/api/*": {"origins": ["http://boostrank.me", "http://www.boostrank.me"]}})
    db.init_app(app)
    
    # Initialize Celery
    celery.conf.update(
        broker_url='redis://localhost:6379/0',
        result_backend='redis://localhost:6379/0',
        task_track_started=True,
        task_time_limit=3600,
        worker_max_tasks_per_child=100,
        broker_connection_retry_on_startup=True
    )
    
    # Create upload and download directories
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['DOWNLOAD_FOLDER'], exist_ok=True)
    
    # Register blueprints
    from app.routes import bp
    app.register_blueprint(bp)
    
    # Create database tables
    with app.app_context():
        db.create_all()
    
    return app 