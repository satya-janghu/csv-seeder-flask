from app import create_app, celery

# Create Flask app instance
app = create_app()

# Push an application context
app.app_context().push()

# This file is used to start the Celery worker 