import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db

app = create_app()

with app.app_context():
    # Create all database tables
    db.create_all()
    print("Database initialized successfully!")

    # Create required directories if they don't exist
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['DOWNLOAD_FOLDER'], exist_ok=True)
    print(f"Created upload directory: {app.config['UPLOAD_FOLDER']}")
    print(f"Created download directory: {app.config['DOWNLOAD_FOLDER']}") 