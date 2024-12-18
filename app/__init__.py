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

def make_celery(app_name=__name__):
    celery = Celery(
        app_name,
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
    return celery

celery = make_celery()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # Updated CORS configuration
    CORS(app, resources={
        r"/api/*": {
            "origins": [
                "http://localhost:3000",
                "http://127.0.0.1:3000",
                "http://boostrank.me:3000",
                "http://boostrank.me",
                "https://boostrank.me"
            ],
            "methods": ["GET", "POST", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"]
        }
    })
    
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